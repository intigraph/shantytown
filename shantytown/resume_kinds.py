"""Machine-testable resume kinds for released and installed versions (aegis-tdf).

    release:<owner>/<repo>@<tag>   met once that GitHub release is published (not a draft)
    release:forgejo:<host>/<owner>/<repo>@<tag>  exact configured Forgejo origin
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
import os
import urllib.request
import re
import shutil
import subprocess
from datetime import datetime
from urllib.parse import urlsplit

#: Stack tools whose own `--version` may be read. Nothing else is executed.
TOOLS = ("sd", "st", "quipu", "bobbin", "yupana", "camayoc", "tambo", "dp")
TIMEOUT = 15

_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
_INSTALLED = re.compile(r"(" + "|".join(TOOLS) + r")(>=|>|==|@)(\d+(?:\.\d+){0,2})")
# A version starts at a token edge or after a `v` (v0.14.0 must not read as 14.0)
# and may carry a pre-release tail (0.15.0-rc.1), which sorts BEFORE its release.
_VERSION = re.compile(r"(?<![\w.])v?(\d+)\.(\d+)(?:\.(\d+))?(-[0-9A-Za-z.-]+)?(?!\w|\.\d)")


def validate(kind: str, arg: str) -> None:
    """Refuse a malformed argument at write time, so it is never stored untestable."""
    if kind == "release":
        repo, sep, tag = arg.rpartition("@")
        if repo.startswith("forgejo:"):
            host, slash, repo = repo[len("forgejo:"):].partition("/")
            if not slash or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
                raise ValueError("Forgejo release needs an exact host/owner/repo@tag")
        if (not sep or not _REPO.fullmatch(repo)
                or repo.split("/")[-1] in (".", "..") or not _TAG.fullmatch(tag)):
            raise ValueError("release:<owner>/<repo>@<tag> needs owner/repo@tag or forgejo:host/owner/repo@tag")
    elif kind == "installed":
        if not _INSTALLED.fullmatch(arg):
            raise ValueError("installed:<tool><op><version> needs one of "
                             f"{', '.join(TOOLS)}, an operator @ >= > == and a version like 0.15.0")
    else:
        raise ValueError(f"not a version kind: {kind}")


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, check=False)


def _parse(text: str):
    """(major, minor, patch, released) from a tool's output, or None.

    `released` is 0 for a pre-release, so 0.15.0-rc.1 < 0.15.0 as in semver.
    """
    m = _VERSION.search(text or "")
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    return (int(major), int(minor), int(patch or 0), 0 if pre else 1)


def _wanted(version: str):
    """The validated wanted version, padded: `1` and `1.0` both mean 1.0.0."""
    parts = [int(p) for p in version.split(".")]
    return tuple(parts + [0] * (3 - len(parts))) + (1,)


def release(arg: str, run=_run):
    """(met, reason): True published, False not yet, None UNKNOWN."""
    validate("release", arg)
    if arg.startswith("forgejo:"):
        return forgejo_release(arg)
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


def forgejo_release(arg: str, *, env=None, opener=None):
    """Read one exact release from the configured origin; never follow redirects.

    This fact condition grants no release authority and registers no event binding.
    Host identity is stored in the condition so a configuration change cannot
    silently move a deferred prerequisite to another forge.
    """
    validate("release", arg)
    if not arg.startswith("forgejo:"):
        return None, "not a Forgejo release condition"
    env = os.environ if env is None else env
    host, _, target = arg[len("forgejo:"):].partition("/")
    repo, _, tag = target.rpartition("@")
    base = env.get("SHANTY_FORGEJO_URL", "").rstrip("/")
    try:
        origin = urlsplit(base)
        valid = (origin.scheme in ("http", "https") and origin.hostname == host.lower()
                 and not origin.username and not origin.password
                 and not origin.path and not origin.query and not origin.fragment
                 and origin.port != 0)
    except ValueError:
        valid = False
    if not valid:
        return None, "Forgejo configured origin missing or mismatched"
    url = f"{base}/api/v1/repos/{repo}/releases/tags/{tag}"
    headers = {"Accept": "application/json"}
    token = env.get("SHANTY_FORGEJO_TOKEN")
    if token:
        headers["Authorization"] = "token " + token
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    reader = opener or urllib.request.build_opener(NoRedirect())
    try:
        with reader.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as response:
            if response.geturl() != url:
                return None, "Forgejo release response changed origin or scope"
            body = response.read(262145)
        if len(body) > 262144:
            return None, "Forgejo release response exceeded byte bound"
        data = json.loads(body)
    except (OSError, ValueError) as exc:
        # An authenticated 404 can also conceal a private repository. Without
        # a separate repository-read proof it cannot establish release absence.
        return None, f"Forgejo release read failed ({type(exc).__name__})"
    if not isinstance(data, dict) or data.get("tag_name") != tag:
        return None, "Forgejo release named a different tag"
    expected = f"{base}/{repo}/releases/tag/{tag}"
    if data.get("html_url") != expected or type(data.get("draft")) is not bool:
        return None, "Forgejo release identity or draft evidence incomplete"
    if data["draft"]:
        return False, f"{host}/{repo} {tag} remains a draft"
    published = data.get("published_at")
    try:
        stamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("timezone required")
    except (AttributeError, TypeError, ValueError):
        return None, "Forgejo publication timestamp missing or malformed"
    return True, f"{host}/{repo} {tag} published {published}"


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
    need = _wanted(want)
    ok = {"@": have >= need, ">=": have >= need, ">": have > need, "==": have == need}[op]
    shown = ".".join(map(str, have[:3])) + ("" if have[3] else " (pre-release)")
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
