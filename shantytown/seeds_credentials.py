"""Explicit Seeds child adapter; selected credentials never fall back in-call.

This module is opt-in. It does not change the tracker or ordinary ``sd`` routing.
The native CLI must admit its own resolved destination before provider access.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import subprocess
import sys

from . import crew_credentials as credentials

_INPUTS = (
    "SEEDS_QUIPU_TOKEN", "SEEDS_QUIPU_TOKEN_FILE",
    "SEEDS_TOKEN", "QUIPU_AUTH_TOKEN", "QUIPU_AUTH_TOKEN_FILE",
    "SEEDS_QUIPU_CREDENTIAL_PRINCIPAL", "SEEDS_QUIPU_TOKEN_FD",
    "SEEDS_QUIPU_CREDENTIAL_DESTINATION",
)


def run(args, *, root, agent, binary="sd", env=None, cwd=None, fetch=None,
        runner=subprocess.run):
    """Run one command, preserving the parent and closing our FD on every exit.

    ``fetch``/``runner`` are trusted Python test seams, never project callbacks.
    Explicit deselection uses native user/config defaults after removing ambient
    bearer/selection inputs; this adapter does not reinterpret inherited inputs
    as deliberate overrides. Use the native explicit API for those overrides.
    """
    child = dict(os.environ if env is None else env)
    for key in _INPUTS:
        child.pop(key, None)
    selected = credentials.selection(root, agent)
    row = selected[1] if selected is not None else {}
    ref = row.get("quipu_cli")
    command = [binary, *args]
    if not args or "--credential-admission" in args:
        raise credentials.Unavailable("invalid Seeds adapter invocation")
    if ref is None:
        return runner(command, env=child, cwd=cwd, capture_output=True, timeout=60)
    if (not hasattr(os, "memfd_create") or not hasattr(fcntl, "F_ADD_SEALS")):
        raise credentials.Unavailable("private descriptor transport unavailable")
    # Same argv/cwd/environment as the final command, with only a native no-I/O
    # flag added. Old CLIs refuse here, before fetching or creating a descriptor.
    admission = runner([*command, "--credential-admission"], env=child, cwd=cwd,
                       capture_output=True, timeout=10)
    if admission.returncode or len(admission.stdout) > 65536:
        raise credentials.Unavailable("Seeds destination admission unavailable")
    try:
        proof = json.loads(admission.stdout)
    except (ValueError, TypeError):
        raise credentials.Unavailable("invalid Seeds destination admission") from None
    if (not isinstance(proof, dict)
            or proof.get("contract") != "seeds-credential-admission/v1"
            or proof.get("admitted") is not True
            or proof.get("destination_binding") is not True
            or not isinstance(proof.get("destination"), str)
            or not proof["destination"] or len(proof["destination"]) > 4096):
        raise credentials.Unavailable("invalid Seeds destination admission")
    # Do not use headers(): it deliberately has a same-call shared fallback for
    # the MCP contract. This command's selection has stricter failure semantics.
    try:
        value = credentials._token((fetch or credentials._fetch)(selected[0], ref))
        if (not value.isascii() or any(not 33 <= ord(c) <= 126 for c in value)
                or not hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(),
                                           ref["token_sha256"])):
            raise ValueError
    except Exception:
        raise credentials.Unavailable("selected Seeds credential unavailable") from None
    fd = os.memfd_create("seeds-command", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.fchmod(fd, 0o600)
        raw = value.encode("ascii")
        if os.write(fd, raw) != len(raw):
            raise credentials.Unavailable("private descriptor write incomplete")
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
                    fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        child.update(SEEDS_QUIPU_CREDENTIAL_PRINCIPAL=row["principal"],
                     SEEDS_QUIPU_TOKEN_FD=str(fd),
                     SEEDS_QUIPU_CREDENTIAL_DESTINATION=proof["destination"])
        return runner(command, env=child, cwd=cwd, pass_fds=(fd,),
                      capture_output=True, timeout=60)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description="Opt-in private Seeds command adapter")
    parser.add_argument("--root", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    opts = parser.parse_args()
    args = opts.args[1:] if opts.args[:1] == ["--"] else opts.args
    try:
        result = run(args, root=opts.root, agent=opts.agent)
    except KeyboardInterrupt:
        return 130
    except Exception:
        print("selected Seeds command unavailable", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
