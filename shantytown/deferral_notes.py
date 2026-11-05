"""Pure single-marker notes preparation; retained prose is never discarded."""
import re
import json

MARKER_PREFIX = re.compile(r"resume[_ -]?when\s*[:=]", re.IGNORECASE)
PROVENANCE_PREFIX = "defer_provenance: "


def provenance(actor, at, until):
    return PROVENANCE_PREFIX + json.dumps(
        {"actor": actor, "set_at": at, "until": until}, sort_keys=True)


def parse_provenance(line):
    """Recognize only the writer's informational envelope, never free prose."""
    from .deferrals import parse_stamp
    if not line.startswith(PROVENANCE_PREFIX):
        return None
    try:
        value = json.loads(line[len(PROVENANCE_PREFIX):])
        if (not isinstance(value, dict) or set(value) != {"actor", "set_at", "until"}
                or any(not isinstance(v, str) for v in value.values())
                or not re.fullmatch(r"[A-Za-z0-9_.@/-]*", value["actor"])
                or parse_stamp(value["set_at"]) is None
                or (value["until"] and parse_stamp(value["until"]) is None)
                or line != provenance(value["actor"], value["set_at"], value["until"])):
            return None
        return value
    except (ValueError, TypeError):
        return None

def historical_notes(text: str) -> str:
    return MARKER_PREFIX.sub("historical resume condition:", text)

def canonical_reason(reason: str, condition: str) -> str:
    from .deferrals import parse_condition
    marker = parse_condition(reason)
    if len(MARKER_PREFIX.findall(reason)) == 1 and marker and marker.render() == condition:
        return reason
    return historical_notes(reason).rstrip() + "\nresume_when: " + condition

def merge_deferral_notes(existing: str | None, addition: str) -> tuple[str, bool]:
    old = existing or ""
    if not old.strip():
        return addition, False
    if addition in old and len(MARKER_PREFIX.findall(old)) == 1:
        return old, False
    if old in addition and len(MARKER_PREFIX.findall(addition)) == 1:
        return addition, True
    return historical_notes(old) + "\n\n" + addition, True
