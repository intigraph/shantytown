"""Queue height must not hide current work or promote quoted work to chrome."""
import pytest

from shantytown import input_box, triage
from shantytown.tmux import NullPanes


READY = '› Ask Codex to do anything\n\n  gpt-6 high · /workspace'
WORKING = '• Working (6m 12s • esc to interrupt)'


def queued(distance, working=True, heading='• Queued follow-up inputs'):
    rows = [WORKING if working else '• Finished the turn.', '', heading,
            '  ↳ Continue the assigned work.']
    rows += ['    wrapped queue preview'] * (distance - len(rows))
    return '\n'.join(rows + [READY])


@pytest.mark.parametrize('distance', [10, 20])
@pytest.mark.parametrize('heading', [
    '• Queued follow-up inputs',
    'Messages to be submitted after next tool call',
    '• Messages to be submitted after next tool call (press esc to interrupt and send',
])
def test_queue_cannot_hide_current_work(distance, heading):
    screen = queued(distance, heading=heading)
    assert triage.mid_flight(screen)
    assert input_box._codex_busy(screen)
    panes = NullPanes(screen=screen)
    assert input_box.clear(panes, 'worker').verdict == input_box.BUSY
    assert panes.controls == []


@pytest.mark.parametrize('distance', [10, 20])
def test_idle_queue_does_not_invent_current_work(distance):
    screen = queued(distance, working=False)
    assert not triage.mid_flight(screen)
    assert not input_box._codex_busy(screen)


def test_working_text_in_queue_payload_is_not_current_work():
    screen = queued(20, working=False).replace(
        '  ↳ Continue the assigned work.', '  ↳ ' + WORKING)
    assert not triage.mid_flight(screen)
    assert not input_box._codex_busy(screen)


def test_previous_composer_fences_historical_work_and_queue():
    screen = queued(20) + '\n› Earlier request\n' + '\n'.join(
        ['• Finished the turn.'] + ['ordinary output'] * 10 + [READY])
    assert not triage.mid_flight(screen)
    assert not input_box._codex_busy(screen)


def test_queue_heading_without_arrow_does_not_expand_chrome():
    screen = queued(20).replace('  ↳ Continue the assigned work.', 'quoted heading')
    assert not triage.mid_flight(screen)
    assert not input_box._codex_busy(screen)


def test_two_current_queue_sections_do_not_hide_work():
    screen = queued(20).replace(
        '    wrapped queue preview',
        '• Queued follow-up inputs\n  ↳ Another queued message.', 1)
    assert triage.mid_flight(screen)
    assert input_box._codex_busy(screen)
