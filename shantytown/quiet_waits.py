"""Keep recorded in-progress CI/install waits quiet without changing their state."""
from datetime import datetime, timezone

from .deferrals import evaluate, parse_conditions
from .deferral_notes import MARKER_PREFIX
from .resume_kinds import validate


def ready(rows, *, root=None, now=None, log=lambda text: None):
    candidates = []
    for row in rows:
        notes = row.get("notes") or ""
        conditions = parse_conditions(notes)
        if (row.get("status") != "in_progress" or len(conditions) != 1
                or len(MARKER_PREFIX.findall(notes)) != 1
                or conditions[0].kind not in ("ci-terminal", "installed")):
            continue
        try:
            validate(conditions[0].kind, conditions[0].arg)
        except ValueError:
            continue  # malformed declarations need an owner's correction
        # Reuse the existing bounded, exact-event reader. A timer cannot wake
        # this in-progress shape and evaluating it never writes tracker state.
        candidates.append(dict(row, status="deferred", defer_until=None))
    if not candidates:
        return rows
    try:
        findings = evaluate(candidates, now or datetime.now(timezone.utc), root=root)
        met = {f.bead for f in findings if f.met and not f.read_error and not f.untestable}
    except Exception as exc:
        log(f"quiet-wait observation UNKNOWN ({type(exc).__name__}); recorded waits retained")
        met = set()
    waiting = {row["id"] for row in candidates} - met
    for identifier in sorted(waiting):
        log(f"quiet-wait {identifier}: exact event pending or UNKNOWN; remains in_progress")
    return [row for row in rows if row.get("id") not in waiting]
