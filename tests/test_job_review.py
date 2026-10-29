"""Private keys and RDF fixtures only; no live signing identity or registration."""
from dataclasses import replace
import os
from pathlib import Path

import pytest

pytest.importorskip('rdflib')
from test_gate_verdict import FakeQuipu, HEAD, NODE, GRAPH, NOW
from shantytown import gate_verdict as gv, job_review
from shantytown.actor_identity import IdentityError


@pytest.fixture
def job(tmp_path, monkeypatch):
    principal = 'eph-review-123abc'
    home = tmp_path / 'job'
    key = home / '.local/state/shantytown/verdict-signer.pk8'
    seed = gv.load_or_generate(key)
    value = {'graph': GRAPH, 'signer': 'st-job-verifier.' + principal, 'key': str(key),
             'public_key': gv.public_key(seed).hex(), 'repo': 'o/n', 'pr': 5,
             'pr_node': NODE, 'head': HEAD, 'author_agent': 'lex'}
    spec = {'principal': principal, 'uid': os.geteuid(), 'home': str(home), 'review': value,
            'request': {'job': 'review', 'repo': 'o/n', 'pr': 5}}
    _, pin = job_review.policy(spec)
    monkeypatch.setattr(gv, 'trusted_signers', lambda: {value['signer']: pin})
    q = FakeQuipu()
    q.register(value['signer'], seed)
    gv.write_authorship(quipu=q, graph=GRAPH, node_id=NODE, agent='lex')
    monkeypatch.setattr(gv, 'default_key_path', lambda: pytest.fail('controller default key selected'))
    monkeypatch.setattr(gv, 'load_or_generate', lambda *a: pytest.fail('key generation attempted'))
    return spec, q, seed, pin


def test_own_key_review_is_scoped_verified_and_retry_does_not_write_again(job, monkeypatch):
    spec, q, _, _ = job
    monkeypatch.setenv('ST_VERDICT_KEY', '/synthetic/controller-key')
    proof = job_review.write(spec, 'approve', HEAD, 'https://example.invalid/review', quipu=q, now=NOW)
    assert job_review.confirmed(spec, {'verdict': 'approve', 'review': proof}, quipu=q)
    writes = len(q.knots)
    assert job_review.write(spec, 'approve', HEAD, 'https://example.invalid/review', quipu=q, now=NOW+60) == proof
    assert len(q.knots) == writes
    with pytest.raises(IdentityError, match='different review'):
        job_review.write(spec, 'request-changes', HEAD, '', quipu=q, now=NOW+60)
    assert len(q.knots) == writes


@pytest.mark.parametrize('committed', [False, True])
def test_lost_review_reply_preserves_exact_prepared_record_and_never_resends(job, monkeypatch, committed):
    spec, q, _, _ = job
    original = q.knot
    calls = []
    def lost(turtle, graph):
        calls.append((turtle, graph))
        if committed:
            original(turtle, graph)
        raise gv.VerdictError('synthetic lost reply')
    monkeypatch.setattr(q, 'knot', lost)
    with pytest.raises(gv.VerdictError):
        job_review.write(spec, 'approve', HEAD, '', quipu=q, now=NOW)
    journal = Path(spec['home']) / '.local/state/shantytown/review-result.json'
    before = journal.read_bytes()
    if committed:
        assert job_review.write(spec, 'approve', HEAD, '', quipu=q, now=NOW+60)['head'] == HEAD
    else:
        with pytest.raises(IdentityError, match='no automatic resend'):
            job_review.write(spec, 'approve', HEAD, '', quipu=q, now=NOW+60)
    assert len(calls) == 1 and journal.read_bytes() == before


@pytest.mark.parametrize('fault', ['missing-key', 'public-key', 'readable-key', 'unregistered', 'wrong-head', 'wrong-uid'])
def test_no_controller_key_or_generation_fallback(job, monkeypatch, fault):
    spec, q, _, _ = job
    path = Path(spec['review']['key'])
    if fault == 'missing-key': path.unlink()
    elif fault == 'public-key': spec['review']['public_key'] = '0' * 64
    elif fault == 'readable-key': path.chmod(0o644)
    elif fault == 'unregistered': monkeypatch.setattr(gv, 'trusted_signers', lambda: {})
    elif fault == 'wrong-uid': spec['uid'] += 1
    before = len(q.knots)
    with pytest.raises((IdentityError, OSError)):
        job_review.write(spec, 'approve', 'b' * 40 if fault == 'wrong-head' else HEAD, '', quipu=q, now=NOW)
    assert len(q.knots) == before
    assert not (path.parent / 'review-result.json').exists()


@pytest.mark.parametrize('fault', ['none', 'principal', 'head', 'node', 'author'])
def test_signed_job_key_cannot_claim_another_reviewer_or_target(job, fault):
    spec, q, seed, pin = job
    record = gv.GateApproval(repo='o/n', pr=5, pr_node=NODE, head=HEAD, outcome='approve',
                            by=spec['principal'], recorded_at=gv.now_stamp(NOW), author_agent='lex')
    if fault == 'principal': record = replace(record, by='eph-review-ffffff')
    elif fault == 'head': record = replace(record, head='b' * 40)
    elif fault == 'node':
        record = replace(record, pr_node='PR_other')
        gv.write_authorship(quipu=q, graph=GRAPH, node_id=record.pr_node, agent='lex')
    elif fault == 'author': record = replace(record, author_agent='someone-else')
    gv.write(record, quipu=q, graph=GRAPH, seed=seed, verifier=spec['review']['signer'])
    result = gv.approval(q, repo='o/n', pr=5, node_id=record.pr_node, head=record.head,
                         graph=GRAPH, signers={spec['review']['signer']: pin})
    assert result['approved'] == (fault == 'none')


def test_bare_job_signer_pin_never_acquires_host_wide_authority(job):
    spec, q, seed, _ = job
    record = gv.GateApproval(repo='o/n', pr=5, pr_node=NODE, head=HEAD, outcome='approve',
                            by=spec['principal'], recorded_at=gv.now_stamp(NOW), author_agent='lex')
    gv.write(record, quipu=q, graph=GRAPH, seed=seed, verifier=spec['review']['signer'])
    result = gv.approval(q, repo='o/n', pr=5, node_id=NODE, head=HEAD, graph=GRAPH,
                         signers={spec['review']['signer']: gv.public_key(seed).hex()})
    assert not result['approved']


@pytest.mark.parametrize('fault', ['none', 'duplicate-key', 'wrong-scope', 'bare-job-key'])
def test_v2_operator_pins_are_scoped_and_cannot_alias_host_key(job, tmp_path, fault):
    import json
    from test_gate_verdict import REAL_TRUSTED_SIGNERS
    spec, _, _, pin = job
    pins = {spec['review']['signer']: dict(pin)}
    if fault == 'duplicate-key': pins['st-review.host'] = pin['public_key']
    elif fault == 'wrong-scope': pins[spec['review']['signer']]['principal'] = 'eph-review-ffffff'
    elif fault == 'bare-job-key': pins[spec['review']['signer']] = pin['public_key']
    path = tmp_path / 'operator-pins.json'
    path.write_text(json.dumps({'version': 2, 'signers': pins}))
    path.chmod(0o600)
    assert REAL_TRUSTED_SIGNERS(path, owner=os.geteuid()) == (pins if fault == 'none' else {})


def test_scoped_signature_cannot_manufacture_missing_authority(job):
    import rdflib
    spec, q, seed, pin = job
    record = gv.GateApproval(repo='o/n', pr=5, pr_node=NODE, head=HEAD, outcome='approve',
                            by=spec['principal'], recorded_at=gv.now_stamp(NOW), author_agent='lex')
    gv.write(record, quipu=q, graph=GRAPH, seed=seed, verifier=spec['review']['signer'])
    q.ds.graph(rdflib.URIRef(GRAPH)).remove((rdflib.URIRef(gv.pr_iri(NODE)),
        rdflib.URIRef(gv.AEGIS + 'authoredByAgent'), None))
    result = gv.approval(q, repo='o/n', pr=5, node_id=NODE, head=HEAD, graph=GRAPH,
                         signers={spec['review']['signer']: pin})
    assert not result['approved']
