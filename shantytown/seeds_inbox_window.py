"""Bounded inbox views: count membership without hydrating message metadata."""
from __future__ import annotations

import json
from urllib.parse import quote, unquote

from .answer import Answer
from .query_identity import declared_read_operation
from . import seeds_plate as sp
from .seeds_inbox import LegacyInboxSchema, STATUSES


def _scopes(proof, agent):
    owners = tuple(dict.fromkeys((agent, agent.split('/')[-1])))
    if not agent or any(not owner for owner in owners):
        raise ValueError('empty inbox owner')
    for graph in (proof.graph, proof.graph + '#seeds-ephemeral'):
        for owner in owners:
            for term in (json.dumps(owner), sp._iri(sp.SEEDS + 'principal/' + quote(owner, safe=''))):
                yield graph, (f'?s <{sp.SCHEMA}agent> {term} . '
                              f'?s a <{sp.SCHEMA}Action> . ')


def _messages():
    statuses = ', '.join(json.dumps(s) for s in STATUSES[:-1])
    return (f'?s <{sp.SEEDS}ontology/status> ?status ; <{sp.SCHEMA}name> ?message . '
            f'FILTER(?status IN ({statuses})) '
            f'FILTER(REGEX(STR(?message), {sp.MESSAGE_PATTERN})) ')


def count_query(proof, agent):
    branches = []
    known = ', '.join(json.dumps(s) for s in (*STATUSES, 'tombstone'))
    for graph, scope in _scopes(proof, agent):
        variants = {
            'owned': scope,
            'valid': scope + f'?s <{sp.SEEDS}ontology/status> ?status . '
                     f'FILTER(isLiteral(?status) && sameTerm(?status, STR(?status)) '
                     f'&& ?status IN ({known})) ',
            'message': scope + _messages(),
            'unique': scope + _messages(),
        }
        for kind, pattern in variants.items():
            group = 'union' if kind == 'unique' else graph
            branches.append('{ GRAPH ' + sp._iri(graph) + ' { ' + pattern + ' } '
                            + f'BIND({json.dumps(kind)} AS ?kind) '
                            + f'BIND({json.dumps(group)} AS ?graph) }}')
    for graph in (proof.graph, proof.graph + '#seeds-ephemeral'):
        branches.append('{ GRAPH ' + sp._iri(graph)
                        + f' {{ ?s <{sp.SEEDS}ontology/revision> ?revision }} '
                        + f'BIND("legacy" AS ?kind) BIND({json.dumps(graph)} AS ?graph) }}')
    return ('SELECT ?kind ?graph (COUNT(DISTINCT ?s) AS ?total) WHERE { '
            + ' UNION '.join(branches) + ' } GROUP BY ?kind ?graph')


@declared_read_operation("owner-rows")
def count(proof, agent, *, timeout=30):
    how = 'Seeds inbox membership aggregates; no message field hydration'
    try:
        groups = {}
        graphs = (proof.graph, proof.graph + '#seeds-ephemeral')
        for row in sp._query(proof, count_query(proof, agent), timeout)['rows']:
            key = row.get('kind'), row.get('graph')
            value = row.get('total')
            kind, graph = key
            if (kind not in {'owned', 'valid', 'message', 'unique', 'legacy'}
                    or graph not in (*graphs, 'union')
                    or (graph == 'union') != (kind == 'unique')
                    or type(value) is not int or value < 0 or key in groups):
                raise ValueError('invalid inbox count aggregate')
            groups[key] = value
        if any(groups.get(('legacy', graph), 0) for graph in graphs):
            raise LegacyInboxSchema('positive legacy revision marker')
        for graph in graphs:
            if groups.get(('owned', graph), 0) != groups.get(('valid', graph), 0):
                raise ValueError('unsupported-owner-status')
        total = groups.get(('unique', 'union'), 0)
        if sum(groups.get(('message', graph), 0) for graph in graphs) != total:
            raise ValueError('receipt appears in shared and ephemeral graphs')
        return Answer.complete_read(total, how=how)
    except LegacyInboxSchema:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return Answer.capped(0, how=how, caveat=f'inbox count unreadable: {error}')


@declared_read_operation("owner-rows")
def page_ids(proof, agent, *, limit=100, oldest_first=False, timeout=30):
    """Dated receipts first, with undated receipts last in either direction."""
    how = 'Seeds bounded inbox identity window'
    try:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('inbox window must contain 1..100 IDs')
        branches = []
        for graph, scope in _scopes(proof, agent):
            branches.append('{ GRAPH ' + sp._iri(graph) + ' { ' + scope + _messages()
                            + f'OPTIONAL {{ ?s <{sp.SCHEMA}dateCreated> ?created_at }} }} '
                            + f'BIND({json.dumps(graph)} AS ?graph) }}')
        order = '?created_at' if oldest_first else 'DESC(?created_at)'
        query = ('SELECT DISTINCT (STR(?s) AS ?subject) ?graph ?created_at WHERE { '
                 + ' UNION '.join(branches)
                 + f' }} ORDER BY DESC(BOUND(?created_at)) {order} ?subject ?graph LIMIT {limit}')
        ids, seen = [], set()
        for row in sp._query(proof, query, timeout)['rows']:
            subject, graph = row.get('subject'), row.get('graph')
            if (not isinstance(subject, str) or not subject.startswith(sp.SEEDS + 'item/')
                    or graph not in (proof.graph, proof.graph + '#seeds-ephemeral')):
                raise ValueError('invalid inbox window identity')
            identifier = unquote(subject[len(sp.SEEDS + 'item/'):])
            if not identifier or subject != sp.SEEDS + 'item/' + quote(identifier, safe=''):
                raise ValueError('noncanonical inbox window identity')
            if identifier in seen:
                raise ValueError('duplicate or ambiguous inbox window identity')
            ids.append(identifier)
            seen.add(identifier)
        if len(ids) > limit:
            raise ValueError('inbox window exceeded requested bound')
        return Answer.complete_read(ids, how=how)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return Answer.capped([], how=how, caveat=f'inbox window unreadable: {error}')
