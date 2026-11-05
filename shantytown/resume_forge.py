"""Fixed, read-only forge facts for deferrals (aegis-x8b1).

Markers select an identity, never a host, command, query or credential. A CI
completion is a terminal observation, including failure; it is not merge GO.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime

KINDS = ("pr-merged", "ci-complete")
_REPO = r"(github|forgejo)/([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9._-]{0,99})"
_PR = re.compile(_REPO + r"#([1-9][0-9]{0,9})")
_CI = re.compile(_REPO + r"@([0-9a-f]{40}|[0-9a-f]{64})")
LIMIT = 100
MAX_PAGES = 10
_CONCLUSIONS = {"success", "failure", "cancelled", "neutral", "skipped", "stale",
                "timed_out", "action_required", "startup_failure"}


def validate(kind, arg):
    pattern = _PR if kind == "pr-merged" else _CI if kind == "ci-complete" else None
    match = pattern.fullmatch(arg) if pattern else None
    if not match:
        raise ValueError("use pr-merged:<github|forgejo>/<owner>/<repo>#<number> "
                         "or ci-complete:<github|forgejo>/<owner>/<repo>@<full-lowercase-sha>")
    return match.groups()


class Reader:
    def __init__(self, provider, repo):
        self.provider, self.repo = provider, repo
        self.deadline = time.monotonic() + 20

    def __call__(self, path):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("forge condition read budget exhausted")
        if self.provider == "github":
            out = subprocess.run(["gh", "api", "--method", "GET", f"repos/{self.repo}{path}"],
                                 capture_output=True, text=True, timeout=min(15, remaining), check=False)
            if out.returncode or len(out.stdout) > 1024 * 1024:
                raise ValueError("GitHub read failed or exceeded byte budget")
            return json.loads(out.stdout)
        # Reuse the configured adapter; never turn a marker into a URL or fall
        # back to a guessed localhost service when deployment config is absent.
        from .forgejo import ForgejoTracker
        if not os.environ.get("SHANTY_FORGEJO_URL"):
            raise ValueError("Forgejo read route is not configured")
        return ForgejoTracker(self.repo, timeout=min(15, remaining))._request("GET", path)


def _pages(read, path, field, provider, *, sha=None):
    """Require the whole bounded inventory, not a truncated first-page green."""
    rows, expected = [], None
    for page in range(1, MAX_PAGES + 1):
        separator = "&" if "?" in path else "?"
        size = "per_page" if provider == "github" else "limit"
        body = read(f"{path}{separator}{size}={LIMIT}&page={page}")
        if not isinstance(body, dict) or type(body.get("total_count")) is not int:
            raise ValueError("forge inventory has no complete count")
        if sha is not None and body.get("sha") != sha:
            raise ValueError("status inventory names a different head")
        count, batch = body["total_count"], body.get(field)
        if (count < 0 or count > LIMIT * MAX_PAGES or not isinstance(batch, list)
                or len(batch) > LIMIT or (expected is not None and expected != count)):
            raise ValueError("forge inventory is oversized, changed or malformed")
        expected = count
        rows.extend(batch)
        if len(rows) == expected:
            ids = [row.get("id") for row in rows if isinstance(row, dict)]
            if (len(ids) != len(rows) or any(type(value) is not int for value in ids)
                    or len(set(ids)) != len(ids)):
                raise ValueError("forge inventory has missing or duplicate identities")
            return rows
        if not batch or len(rows) > expected:
            raise ValueError("forge inventory count mismatch")
    raise ValueError("forge inventory page budget exceeded")


def evaluate(kind, arg, *, read=None):
    try:
        provider, repo, target = validate(kind, arg)
        read = read or Reader(provider, repo)
        if kind == "pr-merged":
            data = read(f"/pulls/{target}")
            if (not isinstance(data, dict) or type(data.get("number")) is not int
                    or data["number"] != int(target)
                    or data.get("base", {}).get("repo", {}).get("full_name") != repo
                    or type(data.get("merged")) is not bool):
                return None, "PR identity or merge result is unreadable"
            if not data["merged"]:
                return False, "PR has not merged (closed alone is not merged)"
            if not isinstance(data.get("merged_at"), str) or not data["merged_at"]:
                return None, "merged PR has no merge receipt"
            at = datetime.fromisoformat(data["merged_at"].replace("Z", "+00:00"))
            if at.tzinfo is None:
                return None, "merged PR receipt has no timezone"
            return True, f"{provider}/{repo}#{target} merged {data['merged_at']}"

        # Status contexts and action parents are separate surfaces: an early
        # green context must not hide a queued workflow whose jobs do not exist.
        statuses = _pages(read, f"/commits/{target}/status", "statuses", provider, sha=target)
        runs = _pages(read, f"/actions/runs?head_sha={target}", "workflow_runs", provider)
        checks = (_pages(read, f"/commits/{target}/check-runs", "check_runs", provider)
                  if provider == "github" else [])
        if not statuses and not checks:
            return None, "no exact-head CI observations exist"
        # A provider that ignores head_sha cannot prove this condition. Do not
        # silently filter a partial repository-wide response into an empty yes.
        for run in runs:
            if not isinstance(run, dict) or (run.get("head_sha") or run.get("commit_sha")) != target:
                return None, "workflow inventory is not scoped to the requested head"
            state = run.get("status")
            if state in ("queued", "waiting", "in_progress", "running", "blocked", "pending", "requested"):
                return False, "exact-head workflow is not terminal"
            if state not in ("completed", "success", "failure", "cancelled", "canceled", "skipped"):
                return None, "workflow state is unreadable"
            if state == "completed" and run.get("conclusion") not in _CONCLUSIONS:
                return None, "workflow completion result is unreadable"
        for check in checks:
            if not isinstance(check, dict) or check.get("head_sha") != target:
                return None, "check observation names a different head"
            if check.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"):
                return False, "exact-head check is not terminal"
            if check.get("status") != "completed" or check.get("conclusion") not in _CONCLUSIONS:
                return None, "check completion result is unreadable"
        for status in statuses:
            if not isinstance(status, dict):
                return None, "status observation is malformed"
            state = status.get("state") or status.get("status")
            if state in ("pending", "running", "waiting"):
                return False, "exact-head status is not terminal"
            if state not in ("success", "failure", "error"):
                return None, "status result is unreadable"
        return True, "exact-head CI inventory is terminal; inspect its conclusions before acting"
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as exc:
        # Exception bodies can contain URLs/auth transport details; expose only
        # the category. A read failure is UNKNOWN, never a readiness receipt.
        return None, f"forge resume read UNKNOWN ({type(exc).__name__})"
