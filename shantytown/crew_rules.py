"""Bounded graph-owned responsibilities; no local fallback rulebook.

# arming: library; anchor, its session-start caller and fleet roles consume this.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ._deadline_http import post
from .deployment import deployment_default
from .query_identity import declared_read_operation, read_headers
from .quipu import request_headers, resolve_onto, resolve_server

MAX_BYTES = 512 * 1024


@declared_read_operation("role-responsibilities")
def ask(root, name, params, *, limit=200, timeout=2):
    """One bounded named-query read. Refusal, overflow and malformed are UNKNOWN."""
    body = post(resolve_server(root=root) + "/ask",
                json.dumps({"name": name, "params": params}),
                {**request_headers(), "X-Quipu-Client": "st", **read_headers()},
                timeout=timeout, max_bytes=MAX_BYTES)
    if len(body) > MAX_BYTES:
        raise ValueError("responsibility response byte cap reached")
    result = json.loads(body)
    if (not isinstance(result, dict) or result.get("error") or result.get("truncated") is not False
            or not isinstance(result.get("rows"), list)
            or type(result.get("count")) is not int or result["count"] != len(result["rows"])
            or result["count"] >= limit):
        raise ValueError("named query completeness UNKNOWN")
    return result["rows"]


@dataclass(frozen=True)
class Responsibilities:
    role: str
    summaries: tuple[str, ...] = ()
    unknown: bool = False

    def lines(self):
        if self.unknown or not self.summaries:
            return [f"    {self.role}: UNKNOWN (graph responsibilities unreadable or empty)"]
        return [f"    {self.role}: {summary}" for summary in self.summaries]


def load(root, roles, *, reader=None):
    """Use canonical role IRIs even against an older stored-query parameter."""
    query = deployment_default(root, "SHANTY_RULES_QUERY")
    roles = sorted(set(roles))
    try:
        onto = resolve_onto(root=root)
    except Exception:
        return [Responsibilities(role, unknown=True) for role in roles]
    answer = []
    for role in roles:
        try:
            if not query or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", role):
                raise ValueError("role/query not declared")
            rows = (reader or ask)(root, query, {"role": onto + role})
            if not rows:
                raise ValueError("empty rules read")
            summaries = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("malformed rule row")
                if row.get("topic") != "responsibilities":
                    continue
                if row.get("scope") != onto + role:
                    raise ValueError("role scope unproved")
                if not all(isinstance(row.get(k), str) and row[k].strip()
                           for k in ("rule", "summary", "text")):
                    raise ValueError("responsibility content unproved")
                if row["rule"] in summaries:
                    raise ValueError("duplicate responsibility")
                summaries[row["rule"]] = " ".join(row["summary"].split())
            if not summaries:
                raise ValueError("no scoped responsibility")
            answer.append(Responsibilities(role, tuple(summaries[k] for k in sorted(summaries))))
        except Exception:
            # Do not print remote exception text: it may contain an authority URL.
            answer.append(Responsibilities(role, unknown=True))
    return answer


def render(reports):
    return "\n".join(["  ROLE RESPONSIBILITIES", *(line for r in reports for line in r.lines())])


def load_all(root, roles=()):
    """One all-role read for the administrator's role catalogue surface."""
    try:
        query = deployment_default(root, "SHANTY_RULES_QUERY")
        onto = resolve_onto(root=root)
        if not query:
            raise ValueError("rules query not declared")
        rows = ask(root, query, {"role": "*"})
        names = set(roles)
        for row in rows:
            if row.get("topic") == "responsibilities":
                scope = row.get("scope")
                if not isinstance(scope, str) or not scope.startswith(onto):
                    raise ValueError("foreign role scope")
                names.add(scope[len(onto):])
        if not names:
            raise ValueError("empty role catalogue")
        def selected(_root, _query, params):
            return [r for r in rows if r.get("scope") in (None, params["role"])]
        return load(root, names, reader=selected)
    except Exception:
        return [Responsibilities(role, unknown=True) for role in sorted(set(roles)) or ["roles"]]
