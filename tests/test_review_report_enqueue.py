"""Protected report -> durable enqueue Action, with a private adapter process."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from test_job_review import job  # noqa: F401
from test_review_enqueue import custody  # noqa: F401
from shantytown import cli, config, ephemeral as eph, job_launch, review_enqueue


def test_approve_report_enqueues_exactly_once_through_reaper(custody, monkeypatch):
    root, directory, spec, q, message = custody
    spec.update(controller_root=str(root.resolve()), controller_uid=review_enqueue.os.geteuid())
    rec = dict(name=spec['principal'], job='review', state=eph.LIVE,
               repo=spec['review']['repo'], pr=spec['review']['pr'], head=spec['review']['head'],
               uid_binding={'uid': spec['uid'], 'sha256': 'a' * 64})
    adapter = root / 'adapter.py'
    adapter.write_text('''import json,sys,pathlib
r=json.load(sys.stdin)
p=pathlib.Path(__file__).with_suffix('.calls')
p.write_text(p.read_text()+'enqueue\\n' if p.exists() else 'enqueue\\n')
print(json.dumps(dict(schema=r['schema'],intent=r['intent'],attempt=r['attempt'],state='queued',receipt='native-queue-receipt')))
''')
    policy = SimpleNamespace(review_enqueue_enabled=True,
                             review_enqueue_command=(sys.executable, str(adapter)))
    monkeypatch.setattr(cli.config, 'load_or_default', lambda _: (SimpleNamespace(ephemeral=policy), None))
    monkeypatch.setattr(cli, '_panes', lambda _: SimpleNamespace(exists=lambda _: True))
    monkeypatch.setattr(eph, 'live', lambda _: [rec])
    monkeypatch.setattr(eph, 'reap', lambda *a, **kw: [])
    monkeypatch.setattr(job_launch, 'poll', lambda *a: {})
    monkeypatch.setattr(eph, 'apply_mailbox', lambda *a: (message | {'summary': 'approved'}, None))
    monkeypatch.setattr(job_launch, 'load', lambda _: (spec, 'a' * 64))
    monkeypatch.setattr(review_enqueue.job_review, 'connection', lambda: q)
    endings = []
    monkeypatch.setattr(cli, '_spawn_end', lambda *a, **kw: endings.append(a))
    for _ in range(2):
        assert cli._spawn_reap(SimpleNamespace(root=root), quiet=True) == cli.OK
    assert adapter.with_suffix('.calls').read_text() == 'enqueue\n'
    intent, = directory.glob('*.json')
    assert json.loads(intent.read_text())['state'] == 'queued'
    assert len(endings) == 2  # duplicate delivery still permits independent teardown
    print('two signed APPROVE reports -> adapter calls:', len(adapter.with_suffix('.calls').read_text().splitlines()))
    print('durable intent state:', json.loads(intent.read_text())['state'])


@pytest.mark.parametrize('fault', ['off', 'changes', 'unsigned', 'wrong-head', 'controller'])
def test_disabled_or_unproved_report_cannot_call_action(custody, fault):
    root, directory, spec, q, message = custody
    spec.update(controller_root=str(root.resolve()), controller_uid=review_enqueue.os.geteuid())
    rec = dict(name=spec['principal'], job='review', **{k: spec['review'][k] for k in ('repo','pr','head')})
    if fault == 'changes': message['verdict'] = 'request-changes'
    if fault == 'unsigned': message.pop('review')
    if fault == 'wrong-head': rec['head'] = 'b' * 40
    if fault == 'controller': spec['controller_uid'] += 1
    policy = config.Ephemeral(review_enqueue_enabled=fault != 'off')
    def forbidden(_): pytest.fail('unproved report reached Action')
    if fault in ('off', 'changes'):
        assert review_enqueue.report(root, rec, spec, message, policy, quipu=q, action=forbidden) is None
    else:
        with pytest.raises(review_enqueue.IdentityError):
            review_enqueue.report(root, rec, spec, message, policy, quipu=q, action=forbidden)
    assert not list(directory.glob('*.json'))


def test_lost_action_reply_never_retries(custody):
    root, directory, spec, q, message = custody
    spec.update(controller_root=str(root.resolve()), controller_uid=review_enqueue.os.geteuid())
    rec = dict(name=spec['principal'], job='review', **{k: spec['review'][k] for k in ('repo','pr','head')})
    calls = []
    def lost(_):
        calls.append('remote enqueue may have happened')
        raise TimeoutError()
    policy = config.Ephemeral(review_enqueue_enabled=True)
    with pytest.raises(TimeoutError):
        review_enqueue.report(root, rec, spec, message, policy, quipu=q, action=lost)
    assert review_enqueue.report(root, rec, spec, message, policy, quipu=q, action=lost)['state'] == 'unknown'
    assert len(calls) == 1


def test_enqueue_config_defaults_off_and_requires_adapter(tmp_path):
    assert config.load(tmp_path).ephemeral.review_enqueue_enabled is False
    path = tmp_path / config.CONFIG_NAME
    for body in ('review_enqueue_enabled = "true"', 'review_enqueue_enabled = true',
                 'review_enqueue_command = ["relative"]'):
        path.write_text('[ephemeral]\n' + body + '\n')
        with pytest.raises(config.ConfigError): config.load(tmp_path)
    path.write_text('[ephemeral]\nreview_enqueue_enabled = true\nreview_enqueue_command = ["/test/native-adapter"]\n')
    assert config.load(tmp_path).ephemeral.review_enqueue_command == ('/test/native-adapter',)


@pytest.mark.parametrize('fault', ['intent', 'attempt', 'state', 'malformed', 'exit'])
def test_action_refuses_unbound_or_unproved_receipt(monkeypatch, fault):
    from subprocess import CompletedProcess
    intent = {'id': 'a' * 64, 'attempt': 'b' * 64, 'candidate': {}}
    result = dict(schema='review-enqueue-action/v1', intent=intent['id'],
                  attempt=intent['attempt'], state='queued', receipt='receipt')
    if fault == 'intent': result['intent'] = 'c' * 64
    if fault == 'attempt': result['attempt'] = 'c' * 64
    if fault == 'state': result['state'] = 'merged'
    stdout = '{' if fault == 'malformed' else json.dumps(result)
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw:
                        CompletedProcess(a, 1 if fault == 'exit' else 0, stdout, ''))
    with pytest.raises((review_enqueue.IdentityError, ValueError)):
        review_enqueue.EnqueueAction(('/test/adapter',))(intent)
