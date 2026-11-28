"""A shed owner read must not publish a clean empty plate (y4mc row 10)."""
import json
from types import SimpleNamespace

import pytest

from shantytown import cli
from shantytown.answer import Answer
from shantytown.br import plate_reader
from shantytown.tmux import NullPanes


@pytest.mark.parametrize('flags', [[], ['--short'], ['--json']])
def test_incomplete_owner_read_is_unknown_not_empty(tmp_path, monkeypatch, capsys, flags):
    (tmp_path / 'crew').mkdir()
    (tmp_path / 'crew' / 'worker.json').write_text(json.dumps({'role': 'worker'}))
    tracker = SimpleNamespace(plate_rows=lambda _: Answer.capped(
        [], how='fixture owner query', caveat='HTTP 429 read_not_started'))

    def reader(*args, **kwargs):
        # Exercise the real partial-answer boundary, not a mocked CLI exception.
        return plate_reader(tracker, require_complete=kwargs.get('require_complete', False))

    monkeypatch.setattr(cli, '_plate', reader)
    monkeypatch.setattr(cli, 'Tmux', lambda *a, **k: NullPanes())
    published = []
    monkeypatch.setattr(cli.plate_publish, 'publish', lambda *a, **k: published.append(a))
    code = cli.main(['--root', str(tmp_path), '--backend', 'files',
                     'anchor', 'worker', *flags])
    captured = capsys.readouterr()
    assert code == cli.CANNOT_TELL
    assert 'UNKNOWN' in captured.err and '429' in captured.err
    assert not published
    if '--json' in flags:
        packet = json.loads(captured.out)
        assert packet['availability'] == 'unknown' and packet['item'] is None
        assert '429' in packet['error']
    else:
        assert captured.out == ''
