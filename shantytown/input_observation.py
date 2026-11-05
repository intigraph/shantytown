"""Read-only, text-free evidence for a single composer observation.

The state remains triage's conservative verdict. A diagnostic reason is not
permission to submit, clear, retry a send, or treat an unknown box as empty.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
import subprocess
import time

from . import __version__, triage


@lru_cache(maxsize=1)
def classifier_digest():
    """Identify the classifier bytes without publishing local source paths."""
    try:
        return hashlib.sha256(Path(triage.__file__).read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def classify(screen, *, started_at, observed_at, elapsed_seconds):
    """Explain the existing classifier, retaining no screen or composer text."""
    state = triage.input_state(screen)
    reason = {
        triage.INPUT_EMPTY: "empty-composer",
        triage.INPUT_PLACEHOLDER: "ghost-composer",
        triage.INPUT_QUEUED: "typed-composer",
        triage.INPUT_UNKNOWN: "ambiguous-attributes",
        triage.INPUT_ABSENT: "no-composer-frame",
    }[state]
    return dict(schema=1, state=state, reason=reason,
                busy=triage.mid_flight(screen), started_at=started_at,
                observed_at=observed_at, elapsed_seconds=max(0, elapsed_seconds),
                shantytown_version=__version__, classifier_sha256=classifier_digest())


def capture(panes, pane, *, wall_clock=time.time, monotonic=time.monotonic):
    """Capture once with attributes and a deadline; failures stay UNKNOWN."""
    started, tick = wall_clock(), monotonic()
    try:
        screen = panes.capture(pane, attrs=True, timeout=5, check=True)
        if not isinstance(screen, str):
            reason = "invalid-capture"
        elif len(screen) > 131072:
            reason = "capture-limit"
        else:
            return classify(screen, started_at=started, observed_at=wall_clock(),
                            elapsed_seconds=monotonic() - tick)
    except subprocess.TimeoutExpired:
        reason = "capture-timeout"
    except (OSError, subprocess.SubprocessError):
        reason = "capture-failed"
    return dict(schema=1, state=triage.INPUT_UNKNOWN, reason=reason, busy=None,
                started_at=started, observed_at=wall_clock(),
                elapsed_seconds=max(0, monotonic() - tick),
                shantytown_version=__version__, classifier_sha256=classifier_digest())
