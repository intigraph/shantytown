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
        branches = []
        for graph in graphs:
            branches.append(f'{{ GRAPH {sp._iri(graph)} {{ ?legacy '
                            f'<{sp.SEEDS}ontology/revision> ?revision }} '
                            'BIND("legacy-schema" AS ?problem) }')
            if identifiers is not None:
                scopes = [f'BIND({sp._iri(sp.SEEDS + "item/" + quote(i, safe=""))} AS ?s) '
                          f'?s a <{sp.SCHEMA}Action> . ' for i in identifiers]
            else:
                scopes = []
                statuses = STATUSES if include_closed else STATUSES[:-1]
                status_filter = ', '.join(json.dumps(s) for s in statuses)
                for owner in owners:
                    for term in (json.dumps(owner),
                                 sp._iri(sp.SEEDS + "principal/" + quote(owner, safe=""))):
                        scopes.append(f'?s a <{sp.SCHEMA}Action> ; '
                                      f'<{sp.SCHEMA}agent> {term} ; '
                                      f'<{sp.SEEDS}ontology/status> ?wanted ; '
                                      f'<{sp.SCHEMA}name> ?title . '
                                      f'FILTER(?wanted IN ({status_filter})) '
                                      f'FILTER(REGEX(STR(?title), {sp.MESSAGE_PATTERN})) ')
            for scope in scopes:
                # Every predicate and graph stays constant, as in owner_rows;
                # a variable-predicate graph scan is not a read-count saving.
                for predicate in FIELDS:
                    branches.append(f'{{ GRAPH {sp._iri(graph)} {{ {scope}'
                                    f'?s {sp._iri(predicate)} ?value }} '
                                    f'BIND({json.dumps(graph)} AS ?graph) '
                                    f'BIND({json.dumps(predicate)} AS ?predicate) }}')
        if identifiers is None:
            branches.append('{ { ' + ' UNION '.join(sp._unsupported_owner_branches(proof, agent))
                            + ' } BIND("unsupported-owner-status" AS ?problem) }')
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
