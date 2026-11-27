"""Opt-in local projection reads through the Seeds SDK, never a second applier.

A reader that cannot serve at all (SDK missing, hung, or exiting nonzero) is
reported once and latched for the binding, and the caller takes its direct
read. Without the latch a hung or unconfigured reader cost up to 5s on every
one of the ~15 reads a single `st anchor` makes. A refusal about one query (an
oversized query, a partial or malformed reply) falls back for that read only:
latching it sent every later read of the command back to direct /query, the
traffic this path exists to remove.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from .query_identity import sdk_subprocess_options


def enabled() -> bool:
    value = os.environ.get("ST_SEEDS_PUSH_READS", "0")
    if value not in ("0", "1"):
        raise ValueError("ST_SEEDS_PUSH_READS must be 0 or 1")
    return value == "1"


_REASON_MAX = 300


class ReaderUnavailable(ValueError):
    """The projection reader itself cannot serve, not merely this query."""

#: (quipu_url, graph) -> refusal text, for this process only. A long-lived
#: process must not be pinned to direct reads by one old refusal forever, but
#: st commands are short; a fresh command retries the projection.
_REFUSED: dict[tuple[str, str], str] = {}
#: (quipu_url, graph, reason) already reported for a per-query fallback, so a
#: refusal repeated across reads prints once without latching the reader.
_NOTED: set[tuple[str, str, str]] = set()


def reset() -> None:
    """Forget latched refusals (tests, or a long-lived caller that wants a retry)."""
    _REFUSED.clear()
    _NOTED.clear()


def _binding(proof) -> tuple[str, str]:
    return (str(getattr(proof, "quipu_url", "") or ""), str(getattr(proof, "graph", "") or ""))


def refused(proof) -> str | None:
    """The latched refusal for this binding, if the projection already said no."""
    return _REFUSED.get(_binding(proof))


def fall_back(proof, refusal) -> None:
    """Say that the projection refused and a direct read follows.

    Only a ReaderUnavailable latches the binding; anything else is about this
    query, and the next read still tries the projection."""
    binding = _binding(proof)
    if binding in _REFUSED:
        return
    reason = " ".join(str(refusal).split())[:_REASON_MAX] or type(refusal).__name__
    if isinstance(refusal, ReaderUnavailable):
        _REFUSED[binding] = reason
        print(f"st: seeds push read refused ({reason}); falling back to direct Quipu "
              "reads for this board for the rest of this command", file=sys.stderr)
        return
    if (*binding, reason) in _NOTED:
        return
    _NOTED.add((*binding, reason))
    print(f"st: seeds push read refused ({reason}); this read falls back to a direct "
          "Quipu read", file=sys.stderr)


def _refusal(stderr) -> str:
    """sd's own refusal line, bounded to one line. Discarding it made a
    freshness-budget refusal of a heavy owner-plate read look like a broken
    SDK (aegis-ygz). Prefer the push-read line; else the last non-empty one."""
    text = (stderr or b"")[-16 * 1024:].decode("utf-8", "replace")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return "no reason given"
    pushed = [line for line in lines if "push read UNKNOWN" in line]
    reason = (pushed or lines)[-1]
    if reason.startswith("sd: "):
        reason = reason[4:]
    return reason if len(reason) <= _REASON_MAX else reason[:_REASON_MAX] + "…"


def read(proof, query: str, timeout: int) -> dict:
    """SDK owns config, private IPC and proof validation.

    Every failure raises; none is an empty answer. The caller decides whether a
    direct read follows (seeds_plate._query does)."""
    if not proof.quipu_url or not proof.graph or timeout <= 0:
        raise ValueError("push read UNKNOWN: authoritative board binding missing")
    payload = json.dumps({"query": query}).encode()
    if len(payload) > 60 * 1024:
        raise ValueError("push read UNKNOWN: projection query exceeds budget")
    try:
        child = subprocess.run(
            [os.environ.get("SHANTY_SD_BIN", "sd"), "--quipu", proof.quipu_url,
             "--graph", proof.graph, "read-stream-query"],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=min(timeout, 5), check=False,
            **sdk_subprocess_options(read_operation="push-projection"),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReaderUnavailable("push read UNKNOWN: local SDK unavailable") from error
    if child.returncode:
        raise ReaderUnavailable(
            f"push read UNKNOWN: SDK refused (exit {child.returncode}): "
            f"{_refusal(getattr(child, 'stderr', None))}")
    if len(child.stdout) > 8 * 1024 * 1024:
        raise ValueError("push read UNKNOWN: SDK response exceeded budget")
    try:
        result = json.loads(child.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError("push read UNKNOWN: malformed SDK response") from error
    if not isinstance(result, dict):
        raise ValueError("push read UNKNOWN: malformed SDK response")
    return result
