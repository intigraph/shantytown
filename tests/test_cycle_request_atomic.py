"""Concurrent request receipts must not hide a refused cycle's risk report."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from threading import Barrier

from shantytown import cli, cycle


def test_simultaneous_atomic_saves_have_private_temporary_files(tmp_path, monkeypatch):
    requests = cycle.Requests(tmp_path)
    barrier = Barrier(2)
    replace = os.replace
    def simultaneous_replace(source, destination):
        barrier.wait(timeout=5)
        return replace(source, destination)
    monkeypatch.setattr(os, 'replace', simultaneous_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(requests._save, {name: {'checkpoint': name}})
                for name in ('first', 'second')]
        for job in jobs:
            job.result(timeout=10)
    assert json.loads(requests.path.read_text()) in (
        {'first': {'checkpoint': 'first'}}, {'second': {'checkpoint': 'second'}})
    assert not list(requests.path.parent.glob('*.tmp'))


def test_concurrent_request_and_refusal_preserve_every_agent(tmp_path):
    requests = cycle.Requests(tmp_path)
    barrier = Barrier(4)
    def writer(worker):
        barrier.wait(timeout=5)
        for i in range(10):
            name = f'worker-{worker}-{i}'
            requests.request(name, name)
            assert requests.mark_refused(name, 'dirty', [cycle.TreeRisk('/fixture/'+name, dirty=True)])
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(writer, worker) for worker in range(4)]
        for job in jobs:
            job.result(timeout=20)
    pending = requests.pending()
    assert len(pending) == 40
    assert all(r['refused']['reason'] == 'dirty' for r in pending.values())


def test_refusal_risks_survive_receipt_io_failure(tmp_path, monkeypatch, capsys):
    from test_cycle_fetch_timeout import world
    args, _, _, _, _, actions = world(tmp_path, monkeypatch)
    risk = cycle.TreeRisk('/fixture/unfinished', dirty=True, unpushed=2)
    monkeypatch.setattr(cycle, 'assess', lambda *a, **k:
                        cycle.Verdict('worker', False, reason='work would be lost', risks=[risk]))
    def fail(*a, **k):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(cycle.Requests, '_save', fail)
    assert cli._cmd_cycle(args) == cli.REFUSED
    output = capsys.readouterr().err
    assert risk.render() in output
    assert 'refusal receipt' in output and 'could not' in output
    assert actions == []
