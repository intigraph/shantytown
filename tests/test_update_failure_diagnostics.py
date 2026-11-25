import json
from subprocess import CompletedProcess

import pytest

from shantytown.br import TrackerUpdateError
from shantytown.sd import SdTracker


def test_update_preserves_refusal_after_observe_warning(monkeypatch):
    tracker = SdTracker()
    warning = 'sd: actor/principal mismatch (observe): ' + 'x' * 200
    refusal = 'lane now is full (6 would exceed cap 5); nothing written'
    monkeypatch.setattr(tracker, '_bd_for', lambda *args: CompletedProcess(
        args, 5, '', warning + '\n' + refusal))

    with pytest.raises(TrackerUpdateError) as caught:
        tracker.update('test-item', lane='now')
    error = json.loads(str(caught.value))['error']
    assert error['details']['exit_code'] == 5
    assert refusal in error['details']['stderr']
