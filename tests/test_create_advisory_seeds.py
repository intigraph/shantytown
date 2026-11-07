import io
import json
from types import SimpleNamespace

import pytest

from shantytown import create_advisory as advisory

# Exercise the real adapter against the intercepted fake CLI below. No live
# store command can run: every subprocess is intercepted and its argv checked.
pytestmark = pytest.mark.real_store


@pytest.fixture
def selected_services(monkeypatch):
    calls = []
    monkeypatch.setenv('SHANTY_SD_BIN', 'configured-sd')
    monkeypatch.setenv('BOBBIN_SERVER', 'http://search.invalid')
    monkeypatch.setenv('SHANTY_CREATE_JEV_COMMAND', 'fake-jev')
    monkeypatch.setattr(advisory.urllib.request, 'urlopen', lambda *a, **k:
        io.StringIO(json.dumps(dict(count=1, results=[dict(bead_id='test-42')]))))

    def run(args, **kwargs):
        calls.append(args)
        assert args[0] == 'configured-sd', 'advisory escaped the selected backend'
        assert args[1:3] == ['--quipu', 'http://board.invalid']
        assert '--no-auto-import' not in args
        if 'where' in args:
            data = dict(location_source='--quipu', quipu_url='http://board.invalid',
                        prefix='test', graph='urn:test:board')
        else:
            assert args[-3:] == ['show', 'test-42', '--json']
            data = dict(id='test-42', title='repair the same leak',
                        description='same acceptance', status='open')
        return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr='')

    class Jev:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def call(self, tool, arguments):
            return dict(request=arguments, model='fixture', usage={}, answer=dict(noul=.95))

    monkeypatch.setattr(advisory.subprocess, 'run', run)
    monkeypatch.setattr(advisory, 'JevMCP', Jev)
    return calls


def test_selected_seeds_store_is_proved_and_read_without_legacy_fallback(selected_services):
    result = advisory.evaluate(dict(title='repair leak', tracker=dict(
        backend='seeds', quipu='http://board.invalid', prefix='test')))
    assert result['outcome'] == 'fired'
    assert len(selected_services) == 2
    assert 'where' in selected_services[0]
    assert 'show' in selected_services[1]


def test_unproven_seeds_store_never_becomes_no_match(selected_services):
    with pytest.raises(advisory.TriageError):
        advisory.evaluate(dict(title='repair leak', tracker=dict(
            backend='seeds', quipu='http://board.invalid', prefix='other')))
    assert len(selected_services) == 1


def test_search_failure_has_a_bounded_stage_reason(selected_services, monkeypatch):
    def fail(*a, **k):
        raise OSError('private URL and credential-shaped text must not be logged')
    monkeypatch.setattr(advisory.urllib.request, 'urlopen', fail)
    with pytest.raises(advisory.TriageError, match='search unavailable'):
        advisory.evaluate(dict(title='repair leak'))


def test_task_preserves_selected_seeds_configuration(monkeypatch, tmp_path):
    from shantytown import cli
    from shantytown.sd import SdTracker
    from shantytown.protocols import WorkItem
    tracker = SdTracker(repo=str(tmp_path), quipu='http://board.invalid', prefix='test')
    monkeypatch.setenv('SHANTY_AGENT', 'tester')
    monkeypatch.setattr(cli, '_tracker', lambda _: tracker)
    monkeypatch.setattr(tracker, 'create', lambda title, **k: WorkItem(id='test-1', title=title))
    seen = []
    monkeypatch.setattr(advisory, 'advise', lambda request: seen.append(request) or '')
    assert cli.main(['--root', str(tmp_path / 'root'), 'task', 'repair leak']) == 0
    assert seen[0]['tracker'] == dict(backend='seeds', store=None,
                                    quipu='http://board.invalid', prefix='test')
