"""Read-only schema.org Seeds projections for plates and crew advice.

Never fetch retained import blobs or descriptions. Unsupported/malformed wire
shapes are UNKNOWN; a failed projection must not trigger full-board hydration.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .answer import Answer

SCHEMA = "https://schema.org/"
SEEDS = "https://seeds.local/"
MESSAGE_PATTERN = json.dumps(r"^\s*(inbox:|mail:)")
FIELDS = {
    SCHEMA + "identifier": "id",
    SCHEMA + "name": "title",
    SCHEMA + "agent": "assignee",
    SCHEMA + "dateModified": "updated_at",
    SCHEMA + "keywords": "labels",
    SEEDS + "ontology/status": "status",
    SEEDS + "ontology/priority": "priority",
    SCHEMA + "scheduledTime": "defer_until",
    SEEDS + "ontology/deferUntil": "defer_until",
}


def _iri(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or any(c in value for c in '<>"{}\\\r\n\t '):
        raise ValueError("invalid graph IRI")
    return "<" + value + ">"


def _query(proof, query: str, timeout: int) -> dict:
    headers = {"Content-Type": "application/json", "X-Quipu-Client": "seeds"}
    # Same caller-declared attribution contract as the SDK, never credentials.
    for header, value in (
        (
            "X-Quipu-Agent",
            os.environ.get("SEEDS_AGENT_NAME") or os.environ.get("SHANTY_AGENT"),
        ),
        ("X-Quipu-Session", os.environ.get("SEEDS_SESSION")),
        ("X-Quipu-Task", os.environ.get("SEEDS_TASK")),
    ):
        if value and value.isascii() and not any(c in value for c in "\r\n"):
            headers[header] = value
    request = Request(
        proof.quipu_url.rstrip("/") + "/query",
        data=json.dumps({"query": query}).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("plate query did not succeed")
        body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise ValueError("plate response byte budget reached")
        result = json.loads(body)
    if not isinstance(result, dict):
        raise TypeError("invalid plate response")
    if query.lstrip().startswith("ASK"):
        if type(result.get("result")) is not bool:
            raise ValueError("schema observation unreadable")
        return result
    rows = result.get("rows")
    if (
        result.get("truncated") is not False
        or not isinstance(rows, list)
        or type(result.get("count")) is not int
        or result["count"] != len(rows)
    ):
        raise ValueError("plate query did not prove completeness")
    return result


def uses_native_schema(proof, *, timeout: int = 30) -> bool:
    """A positive legacy revision marker retains the SDK adapter.

    Do not read an older assignedTo/label ledger as an empty schema.org board.
    Unreadable format checks raise; they never authorize a hydration fallback.
    """
    for graph in (proof.graph, proof.graph + "#seeds-ephemeral"):
        query = f"ASK {{ GRAPH {_iri(graph)} {{ ?s <{SEEDS}ontology/revision> ?revision }} }}"
        if _query(proof, query, timeout)["result"]:
            return False
    return True


def _feed_owner_clause(owners: tuple[str, ...]) -> str:
    # queue_state/hauls accepts any crew-path spelling ending in this worker.
    # Principal IRIs encode path slashes, so match both wire representations.
    names = tuple(dict.fromkeys(a.split("/")[-1] for a in owners))
    alternatives = "|".join(re.escape(n) for name in names
                            for n in dict.fromkeys((name, quote(name, safe=""))))
    if not alternatives:
        return "FILTER(false) "
    pattern = json.dumps(r"(^|/|%2F)(" + alternatives + r")$")
    return f"?s <{SCHEMA}agent> ?owner . FILTER(REGEX(STR(?owner), {pattern})) "


def owner_shape_supported(proof, agent: str | tuple[str, ...], *, timeout: int = 30) -> bool:
    branches = []
    if isinstance(agent, tuple):
        clauses = [_feed_owner_clause(agent)] if agent else []
    else:
        clauses = [f"?s <{SCHEMA}agent> {term} . "
                   for owner in dict.fromkeys((agent, agent.split("/")[-1]))
                   for term in (json.dumps(owner),
                                _iri(SEEDS + "principal/" + quote(owner, safe="")))]
    if not clauses:
        return True
    for graph in (proof.graph, proof.graph + "#seeds-ephemeral"):
        for clause in clauses:
            branches.append(
                f"{{ GRAPH {_iri(graph)} {{ {clause} ?s a <{SCHEMA}Action> . "
                f"FILTER NOT EXISTS {{ ?s <{SEEDS}ontology/status> ?state . "
                'FILTER(?state IN ("open", "hooked", "in_progress", "blocked", "deferred", "closed", "tombstone")) } } }'
            )
    return not _query(proof, "ASK { " + " UNION ".join(branches) + " }", timeout)["result"]


def owner_rows(proof, agent: str | None, *, timeout: int = 30,
               feed_owners: tuple[str, ...] | None = None) -> Answer[list[dict]]:
    how = (
        "Seeds owner-scoped plate fields"
        if agent is not None
        else "Seeds ready/active priority fields"
    ) + "; shared and ephemeral graphs"
    if feed_owners is not None:
        how = "Seeds Rule Zero idle-owner/unassigned fields; shared and ephemeral graphs"
    try:
        scope = feed_owners if feed_owners is not None else agent
        if scope is not None and not owner_shape_supported(
            proof, scope, timeout=timeout
        ):
            raise ValueError("owner has an unsupported or absent status")
        graph = proof.graph
        graphs = (graph, graph + "#seeds-ephemeral")
        owners = (
            tuple(dict.fromkeys((agent, agent.split("/")[-1])))
            if agent is not None
            else ()
        )
        if feed_owners is not None:
            owners = tuple(dict.fromkeys(owner for a in feed_owners
                                         for owner in (a, a.split("/")[-1])))
        branches = []
        for g in graphs:
            statuses = (
                ("open", "in_progress")
                if agent is None
                else ("hooked", "in_progress", "open")
            )
            terms = (
                [None]
                if agent is None and feed_owners is None
                else [
                    term
                    for owner in owners
                    for term in (
                        json.dumps(owner),
                        _iri(SEEDS + "principal/" + quote(owner, safe="")),
                    )
                ]
            )
            if feed_owners is not None:
                # Only unassigned open candidates and the candidate workers'
                # own ready/active hauls can affect Rule Zero.
                branches.append(
                    f'{{ GRAPH {_iri(g)} {{ ?s a <{SCHEMA}Action> ; '
                    f'<{SEEDS}ontology/status> "open" . '
                    f'FILTER NOT EXISTS {{ ?s <{SCHEMA}agent> ?owner . '
                    'FILTER(STR(?owner) != "") } '
                    f'FILTER NOT EXISTS {{ ?s <{SCHEMA}name> ?title . '
                    f'FILTER(REGEX(STR(?title), {MESSAGE_PATTERN})) }} }} '
                    f'BIND({json.dumps(g)} AS ?graph) }}'
                )
            if feed_owners is not None:
                terms = [None] if feed_owners else []
            for term in terms:
                owner_clause = (_feed_owner_clause(feed_owners)
                                if feed_owners is not None
                                else (f"?s <{SCHEMA}agent> {term} . " if term else ""))
                for status in statuses:
                    branches.append(
                        f"{{ GRAPH {_iri(g)} {{ {owner_clause}?s a <{SCHEMA}Action> ; "
                        f"<{SEEDS}ontology/status> {json.dumps(status)} . "
                        f"FILTER NOT EXISTS {{ ?s <{SCHEMA}name> ?title . "
                        f"FILTER(REGEX(STR(?title), {MESSAGE_PATTERN})) }} }} "
                        f"BIND({json.dumps(g)} AS ?graph) }}"
                    )
        query = (
            "SELECT (STR(?s) AS ?subject) ?graph WHERE { "
            + " UNION ".join(branches)
            + " } LIMIT 10000"
        )
        candidates = _query(proof, query, timeout)["rows"]
        if len(candidates) >= 10000:
            raise ValueError("plate candidate budget reached")
        selected = {}
        for candidate in candidates:
            subject, graph = candidate.get("subject"), candidate.get("graph")
            if (
                not isinstance(subject, str)
                or not subject.startswith(SEEDS + "item/")
                or graph not in graphs
            ):
                raise ValueError("invalid plate candidate")
            if subject in selected and selected[subject] != graph:
                raise ValueError("seed appears in shared and ephemeral graphs")
            selected[subject] = graph
        wire = []
        pairs = list(selected.items())
        # Discover scoped IDs first, then bind every subject and predicate.
        # This follows the SDK's indexed query shapes without hydration.
        for offset in range(0, len(pairs), 25):
            fields = []
            for subject, graph in pairs[offset : offset + 25]:
                for predicate in FIELDS:
                    fields.append(
                        f"{{ GRAPH {_iri(graph)} {{ {_iri(subject)} {_iri(predicate)} ?value }} "
                        f"BIND({_iri(subject)} AS ?s) BIND({_iri(predicate)} AS ?p) "
                        f"BIND({json.dumps(graph)} AS ?graph) }}"
                    )
            query = (
                "SELECT (STR(?s) AS ?subject) ?graph (STR(?p) AS ?predicate) ?value WHERE { "
                + " UNION ".join(fields)
                + " } LIMIT 10000"
            )
            part = _query(proof, query, timeout)["rows"]
            if len(part) >= 10000 or len(wire) + len(part) >= 10000:
                raise ValueError("plate field budget reached")
            wire.extend(part)
        grouped = {}
        subjects = {}
        for field in wire:
            subject, g, p, value = (
                field.get(k) for k in ("subject", "graph", "predicate", "value")
            )
            if (
                not isinstance(subject, str)
                or not subject.startswith(SEEDS + "item/")
                or g not in graphs
                or selected.get(subject) != g
                or p not in FIELDS
            ):
                raise ValueError("invalid plate field")
            if subject in subjects and subjects[subject] != g:
                raise ValueError("seed appears in shared and ephemeral graphs")
            subjects[subject] = g
            row = grouped.setdefault(subject, {"labels": []})
            key = FIELDS[p]
            if isinstance(value, dict):
                if set(value) != {"datatype", "value"} or key not in (
                    "updated_at",
                    "defer_until",
                ):
                    raise ValueError("unsupported typed plate value")
                value = value["value"]
            if (
                key == "assignee"
                and isinstance(value, str)
                and value.startswith(SEEDS + "principal/")
            ):
                from urllib.parse import unquote

                value = unquote(value[len(SEEDS + "principal/") :])
            if key == "labels":
                if not isinstance(value, str):
                    raise ValueError("invalid label")
                if value not in row[key]:
                    row[key].append(value)
            else:
                if key in row and row[key] != value:
                    raise ValueError("ambiguous plate field")
                row[key] = value
        if set(grouped) != set(selected):
            raise ValueError("plate candidate disappeared during projection")
        rows = []
        for subject, row in grouped.items():
            if row.get("status") in ("closed", "tombstone"):
                continue
            if (
                not all(isinstance(row.get(k), str) for k in ("id", "title", "status"))
                or not row["id"].strip()
                or (agent is not None and row.get("assignee") not in owners)
                or (feed_owners is not None and row.get("assignee")
                    and row["assignee"].split("/")[-1]
                    not in {a.split("/")[-1] for a in feed_owners})
                or ("assignee" in row and not isinstance(row["assignee"], str))
                or type(row.get("priority")) is not int
                or not 0 <= row["priority"] <= 4
                or row["status"]
                not in (
                    "open",
                    "hooked",
                    "in_progress",
                    "blocked",
                    "deferred",
                    "closed",
                    "tombstone",
                )
                or subject != SEEDS + "item/" + quote(row["id"], safe="")
            ):
                raise ValueError("incomplete or unsupported plate candidate")
            if row["status"] not in ("closed", "tombstone"):
                rows.append(row)
        return Answer.complete_read(rows, how=how)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return Answer.capped([], how=how, caveat=f"owner plate unreadable: {error}")


def unassigned_counts(proof, *, timeout: int = 30) -> tuple[int, int]:
    """Exact open/unassigned counts without fetching any issue payload."""
    graphs = (proof.graph, proof.graph + "#seeds-ephemeral")
    counts = []
    for top in (False, True):
        branches = []
        for graph in graphs:
            priority = (
                f"?s <{SEEDS}ontology/priority> ?priority . FILTER(?priority <= 1) "
                if top
                else ""
            )
            branches.append(
                f'{{ GRAPH {_iri(graph)} {{ ?s <{SEEDS}ontology/status> "open" ; '
                f"a <{SCHEMA}Action> . FILTER NOT EXISTS {{ ?s <{SCHEMA}agent> ?owner . "
                'FILTER(STR(?owner) != "") } ' + priority + "} }"
            )
        query = (
            "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { "
            + " UNION ".join(branches)
            + " }"
        )
        rows = _query(proof, query, timeout)["rows"]
        if len(rows) != 1 or type(rows[0].get("n")) is not int or rows[0]["n"] < 0:
            raise ValueError("unassigned count unreadable")
        counts.append(rows[0]["n"])
    if counts[1] > counts[0]:
        raise ValueError("unassigned counts changed during observation")
    return tuple(counts)


def unblocked_ids(proof, rows: list[dict], *, timeout: int = 30) -> set[str]:
    """SDK-native readiness test on already projected IDs, in bounded batches.

    As in sd ready, an absent blocker status is not an open blocker. Only the
    native blocks predicate participates; related/parent links do not gate it.
    """
    result = set()
    graphs = (proof.graph, proof.graph + "#seeds-ephemeral")
    for offset in range(0, len(rows), 25):
        expected = {row["id"] for row in rows[offset : offset + 25]}
        branches = []
        for row in rows[offset : offset + 25]:
            subject = _iri(SEEDS + "item/" + quote(row["id"], safe=""))
            for graph in graphs:
                branches.append(
                    f"{{ GRAPH {_iri(graph)} {{ {subject} <{SEEDS}ontology/status> {json.dumps(row['status'])} ; "
                    f"a <{SCHEMA}Action> ; <{SCHEMA}identifier> ?id . "
                    f"FILTER NOT EXISTS {{ {subject} <https://scbrown.github.io/quechua/ns#blockedOn> ?blocker . "
                    f"?blocker <{SEEDS}ontology/status> ?bs . "
                    'FILTER(?bs != "closed" && ?bs != "tombstone") } } }'
                )
        query = (
            "SELECT DISTINCT ?id WHERE { " + " UNION ".join(branches) + " } LIMIT 1000"
        )
        wire = _query(proof, query, timeout)["rows"]
        if len(wire) >= 1000 or any(
            not isinstance(r.get("id"), str) or r["id"] not in expected for r in wire
        ):
            raise ValueError("invalid readiness response")
        result.update(r["id"] for r in wire)
    return result
