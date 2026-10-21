"""Machine-testable resume kinds for released and installed versions (aegis-tdf).

    release:<owner>/<repo>@<tag>   met once that GitHub release is published (not a draft)
    installed:<tool><op><version>  met once an allowlisted tool reports a version
                                   satisfying <op>: `@` or `>=` (at least), `>` or `==`

These sit beside `closed:` and `date:` rather than in resume_events: those are
per-item reviewed producer contracts, while these are generic facts anyone can
check. The item's text never selects a command, path or URL. The repository and
tag must match fixed patterns, the tool must be on a fixed allowlist, and the argv
is fixed. Any answer that is not a clean yes or no is UNKNOWN (None), which keeps
the deferral held: reporting a condition met on a read that failed would release
work whose prerequisite may not exist yet.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

#: Stack tools whose own `--version` may be read. Nothing else is executed.
TOOLS = ("sd", "st", "quipu", "bobbin", "yupana", "camayoc", "tambo", "dp")
TIMEOUT = 15

_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
_INSTALLED = re.compile(r"(" + "|".join(TOOLS) + r")(>=|>|==|@)(\d+(?:\.\d+){0,2})")
_VERSION = re.compile(r"\b(\d+)\.(\d+)(?:\.(\d+))?\b")


def validate(kind: str, arg: str) -> None:
    """Refuse a malformed argument at write time, so it is never stored untestable."""
    if kind == "release":
        repo, sep, tag = arg.rpartition("@")
        if not sep or not _REPO.fullmatch(repo) or not _TAG.fullmatch(tag):
            raise ValueError("release:<owner>/<repo>@<tag> needs a GitHub repository and a tag")
    elif kind == "installed":
        if not _INSTALLED.fullmatch(arg):
            raise ValueError("installed:<tool><op><version> needs one of "
                             f"{', '.join(TOOLS)}, an operator @ >= > == and a version like 0.15.0")
    else:
        raise ValueError(f"not a version kind: {kind}")


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, check=False)


def _parse(text: str):
    m = _VERSION.search(text or "")
    return tuple(int(g or 0) for g in m.groups()) if m else None


def release(arg: str, run=_run):
    """(met, reason): True published, False not yet, None UNKNOWN."""
    validate("release", arg)
    repo, _, tag = arg.rpartition("@")
    try:
        out = run(["gh", "api", f"repos/{repo}/releases/tags/{tag}"])
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"release read failed ({type(exc).__name__})"
    if out.returncode != 0:
        # 404 is the one failure that is an answer: the release does not exist yet.
        if "HTTP 404" in (out.stderr or "") or "Not Found" in (out.stdout or ""):
            return False, f"{repo} has no release {tag} yet"
        return None, f"release read exited {out.returncode}"
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return None, "release read was not JSON"
    if not isinstance(data, dict) or data.get("tag_name") != tag:
        return None, "release read named a different tag"
    if data.get("draft") or not data.get("published_at"):
        return False, f"{repo} {tag} is a draft, not published"
    return True, f"{repo} {tag} published {data['published_at']}"


def installed(arg: str, run=_run, which=shutil.which):
    """(met, reason): True satisfied, False older, None UNKNOWN."""
    validate("installed", arg)
    tool, op, want = _INSTALLED.fullmatch(arg).groups()
    path = which(tool)
    if not path:
        return None, f"{tool} is not on PATH"
    try:
        out = run([path, "--version"])
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{tool} --version failed ({type(exc).__name__})"
    have = _parse(out.stdout) if out.returncode == 0 else None
    if have is None:
        return None, f"{tool} --version gave no version"
    need = _parse(want)
    ok = {"@": have >= need, ">=": have >= need, ">": have > need, "==": have == need}[op]
    shown = ".".join(map(str, have))
    return ok, f"{tool} {shown} {'satisfies' if ok else 'does not satisfy'} {op}{want}"


def evaluate(kind: str, arg: str, run=_run, which=shutil.which):
    try:
        if kind == "release":
            return release(arg, run)
        if kind == "installed":
            return installed(arg, run, which)
    except ValueError as exc:
        return None, str(exc)
    return None, f"not a version kind: {kind}"
