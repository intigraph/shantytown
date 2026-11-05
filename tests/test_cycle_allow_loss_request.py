"""An explicit cycle override survives its one durable request, never the next."""
from argparse import Namespace

from shantytown import cli
from shantytown.cycle import Requests


def test_explicit_override_survives_request_and_waiter(tmp_path, monkeypatch):
    requests = Requests(tmp_path)
    requests.request('worker', 'saved checkpoint', allow_loss=True)
    request = requests.pending()['worker']
    seen = []
    monkeypatch.setattr(cli, '_cmd_cycle', lambda args: seen.append(args) or 0)
    assert cli._serve_cycle_request(Namespace(root=tmp_path), 'worker', request) == 0
    assert seen[0].allow_loss is True
    assert seen[0].self_ is False
    assert seen[0].reason == 'saved checkpoint'


def test_override_does_not_leak_into_replacement_request(tmp_path, monkeypatch):
    requests = Requests(tmp_path)
    requests.request('worker', 'first', allow_loss=True)
    requests.request('worker', 'next')
    seen = []
    monkeypatch.setattr(cli, '_cmd_cycle', lambda args: seen.append(args) or 0)
    cli._serve_cycle_request(Namespace(root=tmp_path, allow_loss=True),
                             'worker', requests.pending()['worker'])
    assert seen[0].allow_loss is False


def test_automatic_request_cannot_inherit_override(tmp_path, monkeypatch):
    requests = Requests(tmp_path)
    requests.request('worker', 'auto', allow_loss=True, auto=True)
    request = requests.pending()['worker']
    assert not request.get('allow_loss', False)
    # Even a stale automatic record carrying the field cannot spend it.
    request['allow_loss'] = True
    seen = []
    monkeypatch.setattr(cli, '_cmd_cycle', lambda args: seen.append(args) or 0)
    cli._serve_cycle_request(Namespace(root=tmp_path), 'worker', request)
    assert seen[0].allow_loss is False
