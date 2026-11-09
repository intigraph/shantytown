"""Explicit intake deadlines; never invent a due date from priority or ownership."""
from datetime import datetime, timezone
import re


def deadline(value, required):
    policy = str(required or "").strip().lower()
    if policy not in ("", "0", "false", "no", "off", "1", "true", "yes", "on"):
        raise ValueError("task due-date policy UNKNOWN")
    if value is None:
        if policy in ("1", "true", "yes", "on"):
            raise ValueError("task intake requires --due (date or timezone-qualified instant)")
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        else:
            if not re.match(r"\d{4}-\d{2}-\d{2}T", value):
                raise ValueError()
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        raise ValueError("--due must be YYYY-MM-DD or a timezone-qualified ISO instant") from None
