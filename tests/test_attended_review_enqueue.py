"""Attended signed report -> the existing durable Action, without a job UID."""
import json
import sys
from types import SimpleNamespace

import pytest

from test_ephemeral import store, _st, _attended_review  # noqa: F401
from test_job_review import job  # noqa: F401
from test_review_enqueue import custody  # noqa: F401
from test_gate_verdict import FakeQuipu, HEAD, NODE, GRAPH, SEED, SIGNER, NOW
from shantytown import cli, ephemeral as eph, gate_verdict as gv, review_enqueue


def forge(pr=5):
    return dict(number=pr, node_id=NODE, state='open', head={'sha': HEAD},
                base={'repo': {'full_name': 'o/n'}})


def signed(monkeypatch, principal, pr=5, *, q=None, now=NOW):
    q = q or FakeQuipu()
    q.register(SIGNER, SEED)
    monkeypatch.setattr(gv, 'trusted_signers', lambda: {SIGNER: gv.public_key(SEED).hex()})
    gv.write_authorship(quipu=q, graph=GRAPH, node_id=NODE, agent='lex')
    record = gv.GateApproval(repo='o/n', pr=pr, pr_node=NODE, head=HEAD,
        outcome='approve', by=principal, recorded_at=gv.now_stamp(now), author_agent='lex')
    gv.write(record, quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    return q


def test_attended_signed_approval_uses_one_durable_attempt(custody, monkeypatch):
    root, directory, spec, _, _ = custody
    rec = dict(name=spec['principal'], job='review', state=eph.LIVE,
               harness='codex', repo='o/n', pr=5, head=HEAD)
    q = signed(monkeypatch, rec['name'])
    policy = SimpleNamespace(review_enqueue_enabled=True,
        review_enqueue_command=('/test/adapter',), verdict_graph=GRAPH)
    message = dict(verdict='approve', head=HEAD, signer=SIGNER)
    calls = []
    def action(intent):
        calls.append(intent)
        return 'queued', 'forge-queue-entry'
    for attempt in range(2):
        if attempt:
            signed(monkeypatch, rec['name'], q=q, now=NOW + 60)
        result = review_enqueue.report(root, rec, None, message, policy,
            quipu=q, gh=lambda _: forge(), action=action)
        assert result['state'] == 'queued'
    assert len(calls) == 1
    assert calls[0]['candidate']['record'].startswith(gv.AEGIS)
    assert len(list(directory.glob('*.json'))) == 1
    print('two attended signed approvals, different timestamps -> one adapter call; queued')


def test_attended_lost_reply_does_not_rearm_after_new_signature(custody, monkeypatch):
    root, directory, spec, _, _ = custody
    rec = dict(name=spec['principal'], job='review', state=eph.LIVE,
               harness='codex', repo='o/n', pr=5, head=HEAD)
    q = signed(monkeypatch, rec['name'])
    policy = SimpleNamespace(review_enqueue_enabled=True,
        review_enqueue_command=('/test/adapter',), verdict_graph=GRAPH)
    message = dict(verdict='approve', head=HEAD, signer=SIGNER)
    calls = []
    def lost(intent):
        calls.append(intent)
        raise TimeoutError('remote mutation may have committed')
    with pytest.raises(TimeoutError):
        review_enqueue.report(root, rec, None, message, policy,
                              quipu=q, gh=lambda _: forge(), action=lost)
    signed(monkeypatch, rec['name'], q=q, now=NOW + 60)
    result = review_enqueue.report(root, rec, None, message, policy,
                                  quipu=q, gh=lambda _: forge(), action=lost)
    assert result['state'] == 'unknown' and len(calls) == 1
    assert len(list(directory.glob('*.json'))) == 1
    print('lost adapter reply, later signed approval -> one call; UNKNOWN retained')


@pytest.mark.parametrize('fault', ['head', 'moved', 'unsigned', 'revoked', 'unbound', 'blocked'])
def test_attended_unproved_report_never_calls_action(custody, monkeypatch, fault):
    root, directory, spec, _, _ = custody
    rec = dict(name=spec['principal'], job='review', state=eph.LIVE,
               harness='codex', repo='o/n', pr=5, head=HEAD)
    q = signed(monkeypatch, rec['name'])
    message = dict(verdict='approve', head=HEAD, signer=SIGNER)
    info = forge()
    if fault == 'head': message['head'] = 'b' * 40
    if fault == 'moved': info['head']['sha'] = 'b' * 40
    if fault == 'unsigned': q = FakeQuipu()
    if fault == 'revoked': q.registry.clear()
    if fault == 'unbound': rec.pop('head')
    if fault == 'blocked':
        gv.write(gv.GateApproval(repo='o/n', pr=5, pr_node=NODE, head=HEAD,
            outcome='changes', by='another-reviewer', recorded_at=gv.now_stamp(NOW),
            author_agent='lex'), quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    policy = SimpleNamespace(review_enqueue_enabled=True,
        review_enqueue_command=('/test/adapter',), verdict_graph=GRAPH)
    with pytest.raises(review_enqueue.IdentityError):
        review_enqueue.report(root, rec, None, message, policy, quipu=q,
            gh=lambda _: info, action=lambda _: pytest.fail('unproved Action'))
    assert not list(directory.glob('*.json'))


@pytest.mark.parametrize('fault', [None, 'wrong-head', 'unsigned', 'off', 'command-unset'])
def test_attended_cli_report_preserves_teardown_and_calls_adapter_only_on_proof(
        store, custody, monkeypatch, tmp_path, fault):
    root, _, _ = store
    adapter = tmp_path / 'adapter.py'
    adapter.write_text('''import json,sys,pathlib
r=json.load(sys.stdin)
pathlib.Path(__file__).with_suffix('.calls').write_text('enqueue\\n')
print(json.dumps(dict(schema=r['schema'],intent=r['intent'],attempt=r['attempt'],state='queued',receipt='queue-entry')))
''')
    path = root / 'shantytown.toml'
    text = path.read_text()
    text += '\nverdict_graph = ' + json.dumps(GRAPH)
    text += '\nverdict_signer = ' + json.dumps(SIGNER)
    text += '\nreview_enqueue_enabled = ' + ('false' if fault == 'off' else 'true')
    if fault != 'command-unset':
        text += '\nreview_enqueue_command = ' + json.dumps([sys.executable, str(adapter)])
    path.write_text(text + '\n')
    monkeypatch.setattr(cli, '_gh_json', lambda _: forge(3))
    if fault == 'command-unset':
        assert _st(root, '--ephemeral', '--job', 'review', '--item', 'it-1',
                   '--repo', 'o/n', '--pr', '3') == cli.REFUSED
        assert eph.records(root) == []
        return
    root, rec = _attended_review(store, monkeypatch)
    if fault != 'off': assert rec['head'] == HEAD
    root.chmod(0o700)
    (root / 'ephemeral').chmod(0o700)
    (root / 'ephemeral' / 'review-enqueue').mkdir(mode=0o700)
    q = signed(monkeypatch, rec['name'], 3)
    monkeypatch.setattr(cli, '_spawn_quipu', lambda _: q)
    monkeypatch.setattr(gv, 'load_or_generate', lambda _: SEED)
    monkeypatch.setattr(gv, 'default_key_path', lambda: tmp_path / 'unused-key')
    monkeypatch.setattr(cli, '_spawn_post_review_comment',
                        lambda *a: ('https://example.invalid/review', 'posted'))
    monkeypatch.setattr(review_enqueue.job_review, 'connection', lambda: q)
    errors = []
    original_report = review_enqueue.report
    def diagnose(*args, **kwargs):
        try:
            return original_report(*args, **kwargs)
        except Exception as error:
            errors.append(str(error))
            raise
    monkeypatch.setattr(review_enqueue, 'report', diagnose)
    if fault == 'unsigned':
        monkeypatch.setattr(cli, '_spawn_write_verdict', lambda *a: ('', 'unsigned'))
    head = 'b' * 40 if fault == 'wrong-head' else HEAD
    result = _st(root, '--report', '--verdict', 'approve', '--head', head,
                 '--summary', 'review complete')
    assert result in (cli.OK, cli.CANNOT_TELL)
    final = eph.read(root, rec['name'])
    # Attended report requests detached teardown: ENDING is preserved until the
    # normal reaper verifies the pane/workspace teardown, rather than faking DONE.
    assert final['state'] == eph.ENDING and final['result']['verdict'] == 'approve'
    assert adapter.with_suffix('.calls').exists() is (fault is None), errors
    if fault is None: assert 'Enqueue verified: queue-entry' in final['result']['summary']
