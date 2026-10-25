"""Exact work-item context, read BEFORE semantic search (aegis-ayj).

quipu_search with an exact item ID can answer NO CONTEXT while governed
episodes and rulings are linked to that very item: the search floor measures
similarity, not identity. Measured 2026-10-25: a search for aegis-edp returned
NO CONTEXT, while `?act aegis:aboutWorkItem aegis:aegis-edp` returned eight
governed episodes, its END and its scope rulings among them.

So the identity is read first. Each section is ONE bounded exact-IRI read with
its own outcome: a failed read is UNKNOWN with its reason, never an empty
section, and an empty section names the exact IRI it checked. Semantic search
comes second, for related history.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .seeds_plate import SCHEMA, SEEDS, _iri, _query

PROV = "http://www.w3.org/ns/prov#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
EPISODES = 8
COMMENTS = 3
RULINGS = 10
GIST = 160


@dataclass
class Section:
    name: str
    rows: list = field(default_factory=list)
    unknown: str | None = None   # the reason a read could not be completed
    checked: str = ""            # what an empty answer was read from


@dataclass
class Context:
    item_id: str
    item: object = None
    sections: list = field(default_factory=list)


def _value(cell):
    # Verbose /query rows carry typed literals as {"datatype", "value"}.
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def _rows(proof, query, timeout):
    return [{k: _value(v) for k, v in row.items()}
            for row in _query(proof, query, timeout, verbose=True)["rows"]]


def episodes_query(subject: str, about: str, limit: int = EPISODES) -> str:
    return ("SELECT ?act ?when ?label ?who "
            f"(SUBSTR(STR(?summary), 1, {GIST}) AS ?gist) WHERE {{ "
            f"?act {_iri(about)} {_iri(subject)} . "
            f"OPTIONAL {{ ?act {_iri(PROV + 'generatedAtTime')} ?when }} "
            f"OPTIONAL {{ ?act {_iri(RDFS + 'label')} ?label }} "
            f"OPTIONAL {{ ?act {_iri(PROV + 'wasAssociatedWith')} ?who }} "
            f"OPTIONAL {{ ?act {_iri(RDFS + 'comment')} ?summary }} }} "
            f"ORDER BY DESC(?when) LIMIT {limit}")


def rulings_query(subject: str, tracked_by: str, limit: int = RULINGS) -> str:
    return ("SELECT ?ruling ?label ?type WHERE { "
            f"?ruling {_iri(tracked_by)} {_iri(subject)} . "
            f"OPTIONAL {{ ?ruling {_iri(RDFS + 'label')} ?label }} "
            f"OPTIONAL {{ ?ruling {_iri(TYPE)} ?type }} }} LIMIT {limit}")


def comments_query(graph: str, item: str, limit: int = COMMENTS) -> str:
    return ("SELECT ?position ?when ?author "
            f"(SUBSTR(STR(?text), 1, {GIST}) AS ?gist) WHERE {{ "
            f"GRAPH {_iri(graph)} {{ ?c {_iri(SCHEMA + 'parentItem')} {_iri(item)} . "
            f"OPTIONAL {{ ?c {_iri(SCHEMA + 'position')} ?position }} "
            f"OPTIONAL {{ ?c {_iri(SCHEMA + 'dateCreated')} ?when }} "
            f"OPTIONAL {{ ?c {_iri(SCHEMA + 'author')} ?author }} "
            f"OPTIONAL {{ ?c {_iri(SCHEMA + 'text')} ?text }} }} }} "
            f"ORDER BY DESC(?position) LIMIT {limit}")


def _section(name, checked, read):
    try:
        return Section(name, rows=read(), checked=checked)
    except Exception as exc:  # any failed read is UNKNOWN, not "none found"
        return Section(name, unknown=f"{type(exc).__name__}: {exc}"[:200], checked=checked)


def context(tracker, item_id: str, *, onto: str, timeout: int = 5) -> Context:
    """Read one item's exact context. Raises only for a malformed ID."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", item_id):
        raise ValueError("item ID must be an opaque identifier, not a path")
    from .seeds_item import read_item
    result = Context(item_id)
    try:
        result.item = read_item(tracker, item_id)
    except LookupError as exc:
        result.sections.append(Section("item", unknown=f"item absent: {exc}"))
    except Exception as exc:
        result.sections.append(Section("item", unknown=f"{type(exc).__name__}: {exc}"[:200]))
    try:
        proof = tracker.prove_store()
    except Exception as exc:
        why = f"store unproven: {type(exc).__name__}: {exc}"[:200]
        result.sections.extend(Section(n, unknown=why) for n in ("comments", "episodes", "rulings"))
        return result
    item_iri = SEEDS + "item/" + item_id
    subject = onto + item_id
    result.sections.append(_section(
        "comments", f"{item_iri} in {proof.graph}",
        lambda: _rows(proof, comments_query(proof.graph, item_iri), timeout)))
    result.sections.append(_section(
        "episodes", f"?act <{onto}aboutWorkItem> <{subject}>",
        lambda: _rows(proof, episodes_query(subject, onto + "aboutWorkItem"), timeout)))
    result.sections.append(_section(
        "rulings", f"?ruling <{onto}trackedBy> <{subject}>",
        lambda: _rows(proof, rulings_query(subject, onto + "trackedBy"), timeout)))
    return result


def _line(text):
    return " ".join(str(text or "").split())


def render(ctx: Context) -> str:
    out = [f"EXACT CONTEXT for {ctx.item_id} (read by ID first; semantic search is second)"]
    item = ctx.item
    if item is not None:
        out.append(f"  item: [{item.status}] P{item.priority} {item.title} "
                   f"@{item.assignee or 'unassigned'}"
                   + (f" due {item.due_at}" if item.due_at else ""))
        if item.open_blockers:
            out.append("  blocked on: " + ", ".join(item.open_blockers))
        if item.defer_until:
            out.append(f"  deferred until: {item.defer_until}")
        if item.notes:
            out.append("  notes: " + _line(item.notes)[:400])
    for section in ctx.sections:
        if section.unknown:
            out.append(f"  {section.name}: UNKNOWN ({section.unknown}); "
                       "this is not an empty answer")
            continue
        if not section.rows:
            out.append(f"  {section.name}: 0 found at {section.checked}")
            continue
        out.append(f"  {section.name} ({len(section.rows)}):")
        for row in section.rows:
            if section.name == "episodes":
                out.append(f"    - {row.get('when') or '?'} {row.get('label') or row.get('act')}: "
                           f"{_line(row.get('gist'))}")
            elif section.name == "rulings":
                out.append(f"    - {row.get('label') or row.get('ruling')} ({row.get('type') or '?'})")
            else:
                who = str(row.get('author') or '?').rsplit('/', 1)[-1]
                out.append(f"    - #{row.get('position')} {row.get('when') or '?'} {who}: "
                           f"{_line(row.get('gist'))}")
    out.append("  then: quipu_search for related history. A NO CONTEXT search answer "
               "is not absence; the exact reads above are the authority.")
    return "\n".join(out)
