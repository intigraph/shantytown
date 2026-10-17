"""Opt-in launch-time credentials; persistent configuration contains references only."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import warnings

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
LIMIT = 65536


class Unavailable(ValueError):
    """Diagnostics never include credentials, HTTP bodies, or configured URLs."""


def _private(path, limit=LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > limit):
            raise Unavailable("credential input must be private and user-owned")
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise Unavailable("credential input exceeds limit")
    return value


def _token(value):
    if (not isinstance(value, str) or not value or len(value.encode()) > 4096
            or any(c.isspace() for c in value)):
        raise Unavailable("invalid credential")
    return value


def selection(root, agent):
    """Deployment-owned auth references; never a second MCP server manifest."""
    path = Path(root) / "provision" / "crew-credentials.json"
    try:
        data = json.loads(_private(path))
    except FileNotFoundError:
        return None
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1 or not isinstance(data.get("agents", {}), dict)):
        raise Unavailable("invalid crew credential configuration")
    if data.get("enabled") is not True:
        return None
    row = data.get("agents", {}).get(agent)
    if row is None:
        return None
    if not isinstance(agent, str) or not NAME.fullmatch(agent):
        raise Unavailable("invalid crew name")
    if (not isinstance(row, dict) or not {"principal", "servers"} <= set(row)
            or set(row) - {"principal", "servers", "quipu_cli"}):
        raise Unavailable("invalid crew credential selection")
    if not isinstance(row["principal"], str) or not row["principal"]:
        raise Unavailable("missing crew principal")
    if (not isinstance(row["servers"], dict) or len(row["servers"]) > 8
            or not row["servers"] and "quipu_cli" not in row
            or "quipu_cli" in row and "quipu-cli" in row["servers"]):
        raise Unavailable("invalid crew credential servers")
    audiences, digests = {}, {}
    for name, ref in _entries(row):
        if not NAME.fullmatch(name) or not isinstance(ref, dict):
            raise Unavailable("invalid crew credential server")
        audience = ref.get("audience")
        expected = "CREW_" + hashlib.sha256(row["principal"].encode()).hexdigest()[:24].upper()
        if audience not in ("homelab-mcp", "quipu"):
            raise Unavailable("invalid crew credential audience")
        if name == "quipu-cli" and audience != "quipu":
            raise Unavailable("invalid CLI credential audience")
        expected += "_" + audience.replace("-", "_").upper()
        if (set(ref) != {"audience", "project", "path", "key", "secret_id",
                        "secret_version", "token_sha256", "shared_key"}
                or ref["key"] != expected or ref["path"] != "/mcp-crew/" + agent
                or not isinstance(ref["project"], str)
                or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", ref["project"])
                or not isinstance(ref["secret_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ref["secret_id"])
                or type(ref["secret_version"]) is not int or ref["secret_version"] < 1
                or not isinstance(ref["token_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", ref["token_sha256"])
                or not isinstance(ref["shared_key"], str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]*", ref["shared_key"])):
            raise Unavailable("invalid crew credential reference")
        pin = {k: v for k, v in ref.items() if k != "shared_key"}
        if audience in audiences and audiences[audience] != pin:
            raise Unavailable("conflicting references for one credential audience")
        if ref["token_sha256"] in digests and digests[ref["token_sha256"]] != audience:
            raise Unavailable("credential reused across service audiences")
        audiences[audience] = pin
        digests[ref["token_sha256"]] = audience
    return data, row


def _entries(row):
    return list(row["servers"].items()) + (
        [("quipu-cli", row["quipu_cli"])] if "quipu_cli" in row else [])


def _tmpfs(path):
    """Check the actual Linux mount, not TMPDIR or a user-supplied assertion."""
    target = str(path.resolve())
    matches = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        mount = left.split()[4].replace("\\040", " ").replace("\\134", "\\")
        if target == mount or target.startswith(mount.rstrip("/") + "/"):
            matches.append((len(mount), right.split()[0]))
    return bool(matches) and max(matches)[1] == "tmpfs"


def _directory(agent, *, base=None):
    if not NAME.fullmatch(agent):
        raise Unavailable("invalid crew name")
    base = Path("/run/user") / str(os.getuid()) if base is None else Path(base)
    info = base.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or not _tmpfs(base)):
        raise Unavailable("private runtime tmpfs unavailable")
    for name in ("shantytown-credentials", agent):
        base = base / name
        try:
            base.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = base.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise Unavailable("untrusted runtime credential directory")
    return base


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _request(opener, url, *, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers,
                      data=None if body is None else json.dumps(body).encode())
    with opener.open(request, timeout=5) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise Unavailable("credential response exceeds limit")
    return json.loads(raw)


def _fetch(data, ref):
    server = data.get("server")
    if not isinstance(server, str):
        raise Unavailable("missing credential server")
    url = urlsplit(server)
    if (url.scheme not in ("http", "https") or not url.netloc
            or url.username is not None or url.password is not None
            or url.path not in ("", "/") or url.query or url.fragment
            or any(c.isspace() for c in server)):
        raise Unavailable("invalid credential server")
    # Reuse the existing crew machine identity; never export it to the pane.
    credentials = {}
    for line in _private(Path.home() / ".infisical" / "credentials").decode().splitlines():
        line = line.strip().removeprefix("export ")
        key, sep, value = line.partition("=")
        if sep and key in ("INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET"):
            parts = shlex.split(value)
            if len(parts) != 1 or key in credentials:
                raise Unavailable("invalid credential bootstrap")
            credentials[key] = parts[0]
    opener = build_opener(_NoRedirect)
    base = server.rstrip("/") + "/api"
    login = _request(opener, base + "/v1/auth/universal-auth/login", body={
        "clientId": credentials["INFISICAL_CLIENT_ID"],
        "clientSecret": credentials["INFISICAL_CLIENT_SECRET"]})
    auth = _token(login["accessToken"])
    query = urlencode({"workspaceId": ref["project"], "environment": "prod",
                       "secretPath": ref["path"], "type": "shared"})
    result = _request(opener, base + "/v3/secrets/raw/" + ref["key"] + "?" + query,
                      token=auth)["secret"]
    value = _token(result["secretValue"])
    if (result.get("_id", result.get("id")) != ref["secret_id"]
            or type(result.get("version")) is not int
            or result["version"] != ref["secret_version"]
            or not hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(),
                                       ref["token_sha256"])):
        raise Unavailable("credential reference readback mismatch")
    return value


def project(servers, root, agent, harness, *, fetch=None, materialize=True):
    """Materialize only selected canonical entries at ordinary provision time."""
    selected = selection(root, agent)
    if selected is None:
        return servers
    data, row = selected
    if harness not in ("claude", "codex", None):
        raise Unavailable("crew file credentials unsupported by this harness")
    if set(row["servers"]) - set(servers):
        raise Unavailable("crew credential server absent from canonical tooling")
    runtime = _directory(agent) if materialize else None
    result = {name: dict(spec) for name, spec in servers.items()}
    fetched = {}
    for name, ref in _entries(row):
        if name in row["servers"] and not result[name].get("url"):
            raise Unavailable("crew credential requires HTTP MCP")
        target = runtime / name if materialize else None
        # Remove the prior launch's value first; an unavailable read must never
        # silently reuse stale named credentials.
        if materialize:
            target.unlink(missing_ok=True)
        try:
            if not materialize:
                continue
            audience = ref["audience"]
            if audience not in fetched:
                fetched[audience] = None  # A failed fetch is not resent for another entry.
                fetched[audience] = _token((fetch or _fetch)(data, ref))
            value = _token(fetched[audience])
            if not hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(),
                                       ref["token_sha256"]):
                raise Unavailable("credential reference mismatch")
            with tempfile.NamedTemporaryFile(dir=runtime, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(value.encode())
                    stream.close()
                    os.chmod(temporary, 0o600)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
        except Exception:
            warnings.warn("crew credential unavailable; shared fallback on next connection",
                          RuntimeWarning, stacklevel=2)
        finally:
            if name in row["servers"]:
                _helper(result[name], root, agent, name)
    return result


def _helper(spec, root, agent, name):
    headers = dict(spec.get("headers", {}))
    spec["headers"] = {k: v for k, v in headers.items()
                       if k.lower() != "authorization"}
    spec["headersHelper"] = shlex.join([
        sys.executable, "-m", "shantytown.crew_credentials",
        "--root", str(Path(root).resolve()), "--agent", agent, "--server", name])


def headers(root, agent, server):
    """Called only by the harness's private header-helper pipe."""
    selected = selection(root, agent)
    refs = dict(_entries(selected[1])) if selected is not None else {}
    if server not in refs:
        raise Unavailable("crew credential selection unavailable")
    ref = refs[server]
    try:
        value = _token(_private(_directory(agent) / server, 4096).decode())
        if not hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(),
                                   ref["token_sha256"]):
            raise Unavailable("runtime credential mismatch")
    except Exception:
        # Global shared provider only; never another crew's override.
        from .provision import load_secrets
        value = _token(load_secrets(root).get(ref["shared_key"]))
    return {"Authorization": "Bearer " + value}


def cli_environment(root, agent):
    """Only a file path, never a bearer, crosses the launch boundary."""
    if root is None:
        return {}
    selected = selection(root, agent)
    if selected is None or "quipu_cli" not in selected[1]:
        return {}
    path = Path("/run/user") / str(os.getuid()) / "shantytown-credentials" / agent / "quipu-cli"
    return {"QUIPU_AUTH_TOKEN_FILE": str(path)}


def cli_launch_enabled(root):
    """Keep legacy launch bytes when this deployment has no active selection."""
    if root is None:
        return False
    try:
        data = json.loads(_private(Path(root) / "provision" / "crew-credentials.json"))
    except FileNotFoundError:
        return False
    return data.get("enabled") is True


def managed_cli_path(path):
    """Recognize our reserved runtime namespace without reading its target."""
    if not path:
        return False
    return any(re.match(r"/run/user/[0-9]+/shantytown-credentials(?:/|$)", value)
               for value in (path, os.path.abspath(path)))


def cli_token(root, agent, path):
    """Resolve only our explicitly selected CLI path; other providers stay intact."""
    if not managed_cli_path(path):
        return None
    if not root or not agent:
        raise Unavailable("CLI credential identity unavailable")
    expected = Path("/run/user") / str(os.getuid()) / "shantytown-credentials" / agent / "quipu-cli"
    if str(expected) != path:
        raise Unavailable("CLI credential identity mismatch")
    selected = selection(root, agent)
    if selected is None or "quipu_cli" not in selected[1]:
        raise Unavailable("CLI credential selection unavailable")
    return headers(root, agent, "quipu-cli")["Authorization"].removeprefix("Bearer ")


def main():
    parser = argparse.ArgumentParser(description="Private MCP header helper")
    parser.add_argument("--root", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--server", required=True)
    args = parser.parse_args()
    try:
        result = headers(args.root, args.agent, args.server)
    except Exception:
        print("crew credential header unavailable", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
