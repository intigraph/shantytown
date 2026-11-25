"""Operator directives that no work item tracks, for the administrator's anchor.

# arming: library; `st anchor` calls it for the administrator role only.

The deployment names a stored query with SHANTY_ORPHAN_DIRECTIVES_QUERY. Each row
is one directive (`directive`, optional `label`). The section is ABSENT when the
deployment never declared the query: absent is not the same as empty. A refused,
truncated, malformed or overflowing read renders UNKNOWN, never zero.
"""
from __future__ import annotations

from dataclasses import dataclass

from .deployment import deployment_default
from .query_identity import declared_read_operation

KEY = "SHANTY_ORPHAN_DIRECTIVES_QUERY"
LIMIT = 101   # the stored query returns at most 101 rows; 101 means overflow
SHOWN = 8     # names printed; the count is always exact


@dataclass(frozen=True)
class Orphans:
    names: tuple[str, ...] = ()
    unknown: bool = False

    def lines(self) -> list[str]:
        if self.unknown:
            return ["  ORPHAN DIRECTIVES: UNKNOWN (read failed or incomplete)"]
        if not self.names:
            return ["  ORPHAN DIRECTIVES: none"]
        head = ", ".join(self.names[:SHOWN])
        more = f" (+{len(self.names) - SHOWN} more)" if len(self.names) > SHOWN else ""
        return [f"  ORPHAN DIRECTIVES ({len(self.names)}): no seed tracks these. "
                "Link a seed, file one, or mark the directive standing.",
                f"    {head}{more}"]


@declared_read_operation("orphan-directives")
def ask(root, name, params, *, limit=LIMIT):
    from .crew_rules import named_rows
    return named_rows(root, name, params, limit=limit)


def _local(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1].split(":", 1)[-1]


def load(root, *, reader=None) -> Orphans | None:
    """None = the deployment declared no query (render nothing)."""
    query = deployment_default(root, KEY)
    if not query:
        return None
    try:
        rows = (reader or ask)(root, query, {}, limit=LIMIT)
        names = []
        for row in rows:
            iri = row.get("directive") if isinstance(row, dict) else None
            if not isinstance(iri, str) or not iri.strip():
                raise ValueError("malformed orphan row")
            names.append(_local(iri))
        if len(set(names)) != len(names):
            raise ValueError("duplicate orphan row")
        return Orphans(tuple(names))
    except Exception:
        # Do not print remote exception text: it may contain an authority URL.
        return Orphans(unknown=True)


def render(found: Orphans | None) -> str:
    return "" if found is None else "\n".join(found.lines())
