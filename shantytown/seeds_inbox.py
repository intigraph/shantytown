"""One fresh observation for inbox fields, format and completeness guards.

This is a reader, never a writer or a cache. Receipt acknowledgment still uses
the SDK's normal guarded close after checking fresh identity and ownership.
"""
from __future__ import annotations

import json
from urllib.parse import quote, unquote

from .answer import Answer
from .inbox import is_message
from . import seeds_plate as sp

FIELDS = {sp.SCHEMA + "identifier": "id", sp.SCHEMA + "name": "title",
          sp.SCHEMA + "agent": "assignee", sp.SEEDS + "ontology/status": "status",
          sp.SEEDS + "ontology/priority": "priority", sp.SCHEMA + "dateCreated": "created_at"}
STATUSES = ("open", "hooked", "in_progress", "blocked", "deferred", "closed")


class LegacyInboxSchema(RuntimeError):
    """Positive legacy marker; only this result authorizes SDK compatibility."""


def read(proof, agent: str, *, include_closed=False, identifiers=None,
         timeout=30) -> Answer[list[dict]]:
    how = "Seeds one-observation inbox metadata; shared and ephemeral graphs"
    try:
        owners = tuple(dict.fromkeys((agent, agent.split("/")[-1])))
        if not agent or any(not owner for owner in owners):
            raise ValueError("empty inbox owner")
        if identifiers is not None:
            identifiers = list(dict.fromkeys(identifiers))
            if not identifiers or len(identifiers) > 25 or any(
                    not isinstance(i, str) or not i for i in identifiers):
                raise ValueError("receipt batch must contain 1..25 exact IDs")
        graphs = (proof.graph, proof.graph + "#seeds-ephemeral")
        if identifiers is None:
            rows = sp._query(proof, _owned_query(graphs, owners, include_closed), timeout)["rows"]
            if len(rows) >= 10000:
                raise ValueError("inbox field budget reached")
            if any(r.get("problem") == "legacy-schema" for r in rows):
                raise LegacyInboxSchema("positive legacy revision marker")
            return Answer.complete_read(
                _decode(_owned_fields(rows, graphs, include_closed), graphs,
                        owners, None, include_closed), how=how)
        branches = []
        for graph in graphs:
            branches.append(f'{{ GRAPH {sp._iri(graph)} {{ ?legacy '
                            f'<{sp.SEEDS}ontology/revision> ?revision }} '
                            'BIND("legacy-schema" AS ?problem) }')
            scopes = [f'BIND({sp._iri(sp.SEEDS + "item/" + quote(i, safe=""))} AS ?s) '
                      f'?s a <{sp.SCHEMA}Action> . ' for i in identifiers]
            for scope in scopes:
                # Every predicate and graph stays constant, as in owner_rows;
                # a variable-predicate graph scan is not a read-count saving.
                for predicate in FIELDS:
                    branches.append(f'{{ GRAPH {sp._iri(graph)} {{ {scope}'
                                    f'?s {sp._iri(predicate)} ?value }} '
                                    f'BIND({json.dumps(graph)} AS ?graph) '
                                    f'BIND({json.dumps(predicate)} AS ?predicate) }}')
        rows = sp._query(proof, 'SELECT (STR(?s) AS ?subject) ?graph ?predicate ?value ?problem '
                         'WHERE { ' + ' UNION '.join(branches) + ' } LIMIT 10000', timeout)['rows']
        if len(rows) >= 10000:
            raise ValueError("inbox field budget reached")
        if any(r.get("problem") == "legacy-schema" for r in rows):
            raise LegacyInboxSchema("positive legacy revision marker")
        if any("problem" in r for r in rows):
            raise ValueError("owner has an unsupported or absent status")
        return Answer.complete_read(_decode(rows, graphs, owners, identifiers, include_closed), how=how)
    except LegacyInboxSchema:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return Answer.capped([], how=how, caveat=f"inbox metadata unreadable: {error}")


def _owned_query(graphs, owners, include_closed):
    # Avoid subquery/OPTIONAL joins and anti-joins over the whole board.
    # Each branch starts at one constant recipient and graph.
    branches = []
    wanted = ', '.join(json.dumps(v) for v in (STATUSES if include_closed else STATUSES[:-1]))
    fields = ' '.join(f'OPTIONAL {{ ?s {sp._iri(p)} ?{key} }}' for p, key in FIELDS.items())
    for graph in graphs:
        g = sp._iri(graph)
        for owner in owners:
            for term in (json.dumps(owner), sp._iri(sp.SEEDS + "principal/" + quote(owner, safe=""))):
                scope = f'?s <{sp.SCHEMA}agent> {term} . ?s a <{sp.SCHEMA}Action> . '
                selected = (f'?s <{sp.SEEDS}ontology/status> ?wanted ; <{sp.SCHEMA}name> ?message . '
                            f'FILTER(?wanted IN ({wanted})) FILTER(REGEX(STR(?message), {sp.MESSAGE_PATTERN})) ')
                branches.append('{ GRAPH ' + g + ' { ' + scope + selected + fields + ' } '
                                + f'BIND({json.dumps(graph)} AS ?graph) }}')
                branches.append('{ GRAPH ' + g + ' { ' + scope
                                + f'OPTIONAL {{ ?s <{sp.SEEDS}ontology/status> ?owner_status . '
                                + 'BIND(isLiteral(?owner_status) && sameTerm(?owner_status, STR(?owner_status)) AS ?plain_status) } } '
                                + f'BIND({json.dumps(graph)} AS ?graph) '
                                + 'BIND("owner-status" AS ?kind) }')
        branches.append(f'{{ GRAPH {g} {{ ?legacy <{sp.SEEDS}ontology/revision> ?revision }} '
                        'BIND("legacy-schema" AS ?problem) }')
    return ('SELECT (STR(?s) AS ?subject) ?graph ?id ?title ?assignee ?status '
            '?priority ?created_at ?problem ?kind ?owner_status ?plain_status WHERE { ' + ' UNION '.join(branches) + ' } LIMIT 10000')


def _owned_fields(rows, graphs, include_closed):
    """Check all owned statuses, then decode only selected message fields."""
    grouped, statuses = {}, {}
    for row in rows:
        if "problem" in row:
            raise ValueError("unsupported-owner-status")
        subject, graph = row.get("subject"), row.get("graph")
        if not isinstance(subject, str) or graph not in graphs:
            raise ValueError("invalid inbox owner row")
        if row.get("kind") == "owner-status":
            good = row.get("plain_status") is True and row.get("owner_status") in (*STATUSES, "tombstone")
            key = (subject, graph)
            statuses[key] = statuses.get(key, False) or good
        elif "kind" in row or not any(key in row for key in FIELDS.values()):
            raise ValueError("invalid inbox field row")
        else:
            grouped.setdefault((subject, graph), []).append(row)
    if not all(statuses.values()) or not grouped.keys() <= statuses.keys():
        raise ValueError("unsupported-owner-status")
    fields = []
    for (subject, graph), found in grouped.items():
        for row in found:
            for predicate, key in FIELDS.items():
                if key in row:
                    fields.append({"subject": subject, "graph": graph,
                                   "predicate": predicate, "value": row[key]})
                    if len(fields) >= 10000:
                        raise ValueError("inbox field budget reached")
    return fields


def _decode(wire, graphs, owners, identifiers, include_closed):
    grouped, locations = {}, {}
    for field in wire:
        subject, graph, predicate, value = (field.get(k) for k in
                                          ("subject", "graph", "predicate", "value"))
        if (not isinstance(subject, str) or not subject.startswith(sp.SEEDS + "item/")
                or graph not in graphs or predicate not in FIELDS):
            raise ValueError("invalid inbox field")
        if subject in locations and locations[subject] != graph:
            raise ValueError("receipt appears in shared and ephemeral graphs")
        locations[subject] = graph
        key = FIELDS[predicate]
        if isinstance(value, dict):
            if set(value) != {"datatype", "value"} or key != "created_at":
                raise ValueError("unsupported typed inbox field")
            value = value["value"]
        if key == "assignee" and isinstance(value, str) and value.startswith(sp.SEEDS + "principal/"):
            value = unquote(value[len(sp.SEEDS + "principal/"):])
        row = grouped.setdefault(subject, {})
        if key in row and row[key] != value:
            raise ValueError("ambiguous inbox field")
        row[key] = value
    result = []
    for subject, row in grouped.items():
        if (not all(isinstance(row.get(k), str) and row[k] for k in ("id", "title", "status"))
                or row.get("assignee") not in owners or row["status"] not in STATUSES
                or type(row.get("priority")) is not int or not 0 <= row["priority"] <= 4
                or subject != sp.SEEDS + "item/" + quote(row["id"], safe="")
                or not is_message(row["title"])
                or ("created_at" in row and not isinstance(row["created_at"], str))):
            raise ValueError("incomplete or foreign inbox receipt")
        if identifiers is not None and row["id"] not in identifiers:
            raise ValueError("unexpected receipt ID")
        if identifiers is not None or include_closed or row["status"] != "closed":
            result.append(row)
    if identifiers is not None and {r["id"] for r in result} != set(identifiers):
        raise ValueError("exact inbox receipt missing")
    return result
