"""Advisory operator links, never stored rank or priority mutations."""
from __future__ import annotations
import json
import re

MAX_CANDIDATES = 256
A = "http://aegis.gastown.local/ontology/"
SCHEMA = "https://schema.org/"
SEEDS = "https://seeds.local/"


def query(graph, ids):
    from .seeds_plate import _iri
    ids = set(ids)
    if not ids or len(ids) > MAX_CANDIDATES or any(
            not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", i) for i in ids):
        raise ValueError("directive candidate coverage UNKNOWN")
    values = " ".join(f'({json.dumps(i)} {_iri(SEEDS + "item/" + i)} {_iri(A + i)})' for i in sorted(ids))
    operator = f'?directive a <{A}Directive> ; <{A}directiveKind> "operator" ; '
    return (f'SELECT DISTINCT ?id WHERE {{ VALUES (?id ?item ?direct) {{ {values} }} {{ '
            f'{{ {operator} <{A}trackedBy> ?direct . }} UNION {{ '
            f'GRAPH {_iri(graph)} {{ ?item <{SCHEMA}isPartOf>+ ?epic . '
            f'?epic a <{SCHEMA}Action> ; <{SEEDS}ontology/issueType> "epic" ; <{SCHEMA}identifier> ?epic_id . '
            f'FILTER(isLiteral(?epic_id) && sameTerm(?epic_id, STR(?epic_id))) '
            f'FILTER(STR(?epic) = CONCAT("{SEEDS}item/", STR(?epic_id))) }} '
            f'FILTER NOT EXISTS {{ GRAPH {_iri(graph)} {{ ?item <{SCHEMA}isPartOf>* ?via . '
            f'?via <{SCHEMA}isPartOf>* ?epic . }} GRAPH {_iri(graph + "#seeds-ephemeral")} '
            '{ ?via ?shadow_p ?shadow_o } } '
            f'BIND(IRI(CONCAT("{A}", STR(?epic_id))) AS ?target) '
            f'{operator} <{A}trackedBy> ?target . }} }} }} LIMIT {MAX_CANDIDATES + 1}')



def decode(value, candidates):
    if (not isinstance(value, dict) or value.get('truncated') is not False
            or value.get('error') is not None or value.get('partial', False) is not False
            or not isinstance(value.get('rows'), list)
            or type(value.get('count')) is not int or value['count'] != len(value['rows'])
            or len(value['rows']) > MAX_CANDIDATES):
        raise ValueError('directive response incomplete')
    result = set()
    for row in value['rows']:
        if not isinstance(row, dict) or set(row) != {'id'}:
            raise ValueError('directive response shape UNKNOWN')
        ident = row['id']
        if isinstance(ident, dict):
            if not ((set(ident) == {'type', 'value'} and ident['type'] == 'literal')
                    or (set(ident) == {'value', 'datatype'}
                        and ident['datatype'] == 'http://www.w3.org/2001/XMLSchema#string')):
                raise ValueError('directive identifier type UNKNOWN')
            ident = ident['value']
        if not isinstance(ident, str) or ident not in candidates:
            raise ValueError('foreign directive candidate')
        result.add(ident)
    return result


def annotate(proof, rows, *, timeout=2, reader=None):
    # Never trust a flag inherited from a previous read or persisted input.
    result = [{k: v for k, v in row.items() if k != 'operator_directive'} for row in rows]
    ids = {row.get('id') for row in result}
    if not ids:
        return result
    try:
        text = query(proof.graph, ids)
        if reader is None:
            from .seeds_plate import root_context_query
            reader = root_context_query
        boosted = decode(reader(proof, text, min(timeout, 2)), ids)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return result
    for row in result:
        if row['id'] in boosted:
            row['operator_directive'] = True
    return result
