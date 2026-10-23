"""Prepared inbox projection consumer; the live selection call site is unchanged.

One bounded rows response is one snapshot. There is no paging or read cache.
Exact receipt acknowledgments continue to use seeds_inbox.read directly.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

from .answer import Answer
from .inbox import is_message
from . import seeds_inbox as exact
from . import seeds_plate as sp
from .query_identity import read_headers

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
REQUIRED = {
    **{p: name for p, name in exact.FIELDS.items() if name != "assignee"},
    RDF_TYPE: "type",
}
BYTE_LIMIT = 8 * 1024 * 1024
ROW_LIMIT = 1000


@dataclass(frozen=True)
class Observation:
    answer: Answer[list[dict]]
    tx: int | None
    """The returned snapshot watermark; absent when the exact path was used."""


class ExactRequired(ValueError):
    """An explicit ambiguity permits only a whole-request exact read."""


def _post(proof, payload, timeout):
    headers = {"Content-Type": "application/json", "X-Quipu-Client": "seeds"}
    headers.update(read_headers())
    request = Request(proof.quipu_url.rstrip("/") + "/projections",
                      data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("projection read did not succeed")
        body = response.read(BYTE_LIMIT + 1)
        if len(body) > BYTE_LIMIT:
            raise ValueError("projection response byte budget reached")
        result = json.loads(body)
    if not isinstance(result, dict) or "error" in result or result.get("ignored_fields"):
        raise ValueError("invalid projection response")
    return result


def _declaration(capabilities):
    if not isinstance(capabilities, dict):
        raise ValueError("invalid projection capabilities")
    actions = capabilities.get("actions")
    if actions is None:
        return None
    if not isinstance(actions, list) or any(not isinstance(a, str) for a in actions):
        raise ValueError("invalid projection actions")
    if "rows" not in actions:
        return None
    declarations = capabilities.get("declared")
    if not isinstance(declarations, list):
        raise ValueError("projection declaration unavailable")
    found = [d for d in declarations if isinstance(d, dict) and d.get("name") == "inbox"]
    legacy = [d for d in declarations if isinstance(d, dict) and d.get("name") == "inbox_legacy"]
    if (len(found) != 1 or found[0].get("key") != sp.SCHEMA + "agent"
            or len(legacy) != 1 or legacy[0].get("key") != sp.SEEDS + "ontology/revision"
            or legacy[0].get("columns") != []):
        raise ValueError("inbox projection declaration unavailable")
    columns = found[0].get("columns")
    if not isinstance(columns, list):
        raise ValueError("inbox projection columns unavailable")
    mapping, names = {}, set()
    for column in columns:
        if not isinstance(column, dict):
            raise ValueError("invalid projection column")
        name, predicate = column.get("name"), column.get("predicate")
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name)
                or name in names or not isinstance(predicate, str) or predicate in mapping):
            raise ValueError("ambiguous projection declaration")
        mapping[predicate] = name
        names.add(name)
    if not REQUIRED.keys() <= mapping.keys():
        raise ValueError("inbox projection lacks required evidence columns")
    return {predicate: mapping[predicate] for predicate in REQUIRED}


def _iri_value(value):
    if isinstance(value, dict) and set(value) == {"iri"} and isinstance(value["iri"], str):
        return value["iri"]
    return value


def _aggregate(response, graphs, kind):
    if not isinstance(response, dict):
        raise ValueError("invalid projection aggregate")
    total, tx = response.get("total"), response.get("tx")
    groups, multi = response.get("groups"), response.get("multi_valued_rows")
    if (type(total) is not int or total < 0 or type(tx) is not int or tx <= 0
            or type(multi) is not int or not 0 <= multi <= total
            or response.get("truncated") is not False or not isinstance(groups, list)):
        raise ValueError("projection aggregate did not prove completeness")
    if multi:
        raise ExactRequired("projection contains multiple current values")
    if kind == "legacy":
        if total:
            raise ExactRequired("projection contains a legacy marker")
        if groups:
            raise ValueError("unexpected legacy groups")
        return tx
    counted, seen = 0, set()
    for group in groups:
        if (not isinstance(group, dict) or group.get("graph") not in graphs
                or type(group.get("n")) is not int or group["n"] <= 0
                or type(group.get("plain")) is not bool or "value" not in group):
            raise ValueError("invalid projection proof group")
        key = (group["graph"], json.dumps(group["value"], sort_keys=True))
        if key in seen:
            raise ValueError("duplicate projection proof group")
        seen.add(key)
        value = group["value"]
        if kind == "status":
            if (not group["plain"] or not isinstance(value, str)
                    or value not in (*exact.STATUSES, "tombstone")):
                raise ExactRequired("owner has an unsupported or absent status")
        elif value != {"iri": sp.SCHEMA + "Action"} or group["plain"]:
            raise ExactRequired("owner has an unverified Action type")
        counted += group["n"]
    if counted != total:
        raise ValueError("projection proof totals do not reconcile")
    return tx


def _decode(response, mapping, graphs, owners, include_closed):
    if not isinstance(response, dict):
        raise ValueError("invalid projection snapshot")
    rows, tx = response.get("rows"), response.get("tx")
    multi_count = response.get("multi_valued_rows")
    if (not isinstance(rows, list) or len(rows) > ROW_LIMIT
            or response.get("truncated") is not False
            or type(tx) is not int or tx <= 0
            or type(multi_count) is not int or not 0 <= multi_count <= len(rows)):
        raise ValueError("projection did not prove bounded completeness")
    if multi_count:
        raise ExactRequired("projection contains multiple current values")
    fields, locations, identities = [], {}, set()
    previous = ""
    for row in rows:
        if not isinstance(row, dict) or type(row.get("multi")) is not bool:
            raise ValueError("invalid projection row")
        if row["multi"]:
            raise ExactRequired("projection contains multiple current values")
        entity, graph = row.get("entity"), row.get("graph")
        columns, plain = row.get("columns"), row.get("plain")
        if (not isinstance(entity, str) or not entity.startswith(sp.SEEDS + "item/")
                or graph not in graphs or not isinstance(columns, dict)
                or set(columns) != set(mapping.values()) or not isinstance(plain, dict)
                or set(plain) != set(columns) or any(type(v) is not bool for v in plain.values())
                or any(plain[k] and not isinstance(v, str) for k, v in columns.items())
                or type(row.get("key_plain")) is not bool):
            raise ValueError("invalid projection identity or columns")
        if (entity, graph) in identities:
            raise ValueError("duplicate projection row")
        if entity < previous:
            raise ValueError("projection entity order is invalid")
        previous = entity
        identities.add((entity, graph))
        if entity in locations and locations[entity] != graph:
            raise ExactRequired("receipt appears in shared and ephemeral graphs")
        locations[entity] = graph
        kind = columns[mapping[RDF_TYPE]]
        if (not isinstance(kind, dict) or set(kind) != {"iri"}
                or not isinstance(kind["iri"], str)):
            raise ValueError("invalid projection type encoding")
        if kind != {"iri": sp.SCHEMA + "Action"} or plain[mapping[RDF_TYPE]]:
            raise ExactRequired("projection returned an unverified Action type")
        if isinstance(row.get("key"), str) and not row["key_plain"]:
            raise ExactRequired("projection returned a nonplain recipient")
        agent = _iri_value(row.get("key"))
        if isinstance(agent, str) and agent.startswith(sp.SEEDS + "principal/"):
            agent = unquote(agent[len(sp.SEEDS + "principal/"):])
        if agent not in owners:
            raise ValueError("projection returned a foreign recipient")
        status = columns[mapping[sp.SEEDS + "ontology/status"]]
        if (not isinstance(status, str) or status not in (*exact.STATUSES, "tombstone")
                or not plain[mapping[sp.SEEDS + "ontology/status"]]):
            raise ValueError("owner has an unsupported or absent status")
        for predicate in (sp.SCHEMA + "identifier", sp.SCHEMA + "name"):
            if columns[mapping[predicate]] is not None and not plain[mapping[predicate]]:
                raise ExactRequired("projection returned a nonplain identity field")
        title = columns[mapping[sp.SCHEMA + "name"]]
        if not isinstance(title, str) or not is_message(title) or status == "tombstone":
            continue
        if not include_closed and status == "closed":
            continue
        for predicate, key in exact.FIELDS.items():
            value = agent if key == "assignee" else columns[mapping[predicate]]
            if value is not None:
                fields.append({"subject": entity, "graph": graph,
                               "predicate": predicate, "value": _iri_value(value)})
    return exact._decode(fields, graphs, owners, None, include_closed), tx


def read(proof, agent, *, include_closed=False, timeout=30, post=None) -> Observation:
    """Prepare an enumeration from the advertised v1.3 contract.

    This function is not yet selected by SdTracker. Native declaration coverage
    (including status-less Actions and standalone legacy markers) must be proved
    before the real-server switch. A watermark is evidence, never a write pin.
    """
    post = post or _post
    how = "Seeds inbox projection rows; one bounded snapshot"
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise ValueError("projection read time budget reached")
        return seconds

    def fallback():
        return Observation(exact.read(proof, agent, include_closed=include_closed,
                                      timeout=remaining()), None)

    try:
        if not isinstance(agent, str) or not agent or timeout <= 0:
            raise ValueError("invalid projection recipient or time budget")
        owners = tuple(dict.fromkeys((agent, agent.split("/")[-1])))
        if not all(owners):
            raise ValueError("empty projection recipient")
        graphs = (proof.graph, proof.graph + "#seeds-ephemeral")
        for graph in graphs:
            sp._iri(graph)
        try:
            capabilities = post(proof, {"action": "list"}, remaining())
        except HTTPError as error:
            if error.code not in (404, 405):
                raise
            return fallback()
        mapping = _declaration(capabilities)
        if mapping is None:
            return fallback()
        values = [value for owner in owners for value in
                  (owner, {"iri": sp.SEEDS + "principal/" + quote(owner, safe="")})]
        common = {"name": "inbox", "graphs": list(graphs), "key_in": values}
        typed = {mapping[RDF_TYPE]: [{"iri": sp.SCHEMA + "Action"}]}
        for attempt in range(2):
            try:
                status = post(proof, {**common, "action": "aggregate", "where": typed,
                                     "group_by": mapping[sp.SEEDS + "ontology/status"],
                                     "max_groups": 16}, remaining())
                types = post(proof, {**common, "action": "aggregate",
                                    "group_by": mapping[RDF_TYPE], "max_groups": 16}, remaining())
                legacy = post(proof, {"action": "aggregate", "name": "inbox_legacy",
                                     "graphs": list(graphs), "max_groups": 0}, remaining())
                watermarks = [_aggregate(status, graphs, "status"),
                              _aggregate(types, graphs, "type"),
                              _aggregate(legacy, graphs, "legacy")]
                statuses = exact.STATUSES if include_closed else exact.STATUSES[:-1]
                response = post(proof, {**common, "action": "rows",
                                       "where": {**typed, mapping[sp.SEEDS + "ontology/status"]: list(statuses)},
                                       "columns": list(mapping.values()), "limit": ROW_LIMIT}, remaining())
                rows, tx = _decode(response, mapping, graphs, owners, include_closed)
            except ExactRequired:
                return fallback()
            if all(value == tx for value in watermarks):
                if status["total"] != types["total"]:
                    raise ValueError("projection Action totals do not reconcile")
                expected = sum(g["n"] for g in status["groups"] if g["value"] in statuses)
                if len(response["rows"]) != expected:
                    raise ValueError("projection selection totals do not reconcile")
                return Observation(Answer.complete_read(rows, how=f"{how}; tx={tx}"), tx)
            if attempt:
                return fallback()
        raise AssertionError("unreachable")
    except exact.LegacyInboxSchema:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Response bodies and exception text can contain private values.
        return Observation(Answer.capped([], how=how,
                                       caveat="projection snapshot unavailable or unverified"), None)
