"""An 80x24 job pane must not hide a typed Codex job prompt (aegis-e579).

The fixture is a sanitized live Codex 0.161 capture at tmux's default 80x24:
a 23-line synthetic job prompt fills the composer, the footer row is the
warnings row rather than "? for shortcuts", and the model label is several
words ("GPT-6.1 Terra default"). st read that frame as no input box at all,
so every spawned Codex job failed "typed Codex input not observed".
"""
import os
import stat
import types
from pathlib import Path

from shantytown import cli, input_box, tmux, triage

FIXTURES = Path(__file__).parent / 'fixtures/codex_input'


def clipped():
    return (FIXTURES / 'job-pane-80x24-clipped.txt').read_text()


def body():
    return (FIXTURES / 'job-pane-80x24-body.txt').read_text()


def test_live_job_pane_capture_reads_as_typed_input():
    screen = clipped()
    assert triage.codex_composer(screen) is not None
    assert triage.input_state(screen) == triage.INPUT_QUEUED
    assert input_box._classify(screen)[0] == input_box.TYPED


def test_clipped_job_composer_still_cannot_authorize_a_retry_enter():
    # Only the first Enter, on text st itself just typed into an empty box,
    # may rely on this frame. A clipped body is never exact ownership.
    assert not tmux._codex_owned_input(clipped(), body())


def test_multi_word_model_label_with_warnings_row_is_a_footer():
    prompt = '\x1b[0;1m›\x1b[0m typed fixture\n'
    footer = ('  \x1b[38;2;1;2;3mGPT-6.1 Terra default\x1b[39m · /workspace/x\n'
              '        ⚠ \x1b[38;2;1;2;3m5 warnings\x1b[39m · \x1b[1mf2\x1b[0m to view\n')
    assert triage.input_state(prompt + footer) == triage.INPUT_QUEUED
    prose = '  codex said a lot of words here · /workspace/x\n'
    assert triage.codex_composer(prompt + prose + footer.splitlines()[1]) is None


def test_initial_job_send_presses_enter_on_the_clipped_frame(monkeypatch):
    from tests.test_codex_submission import BUSY, READY, keys, transport
    panes, calls = transport(monkeypatch, [READY, BUSY], typed_frame=clipped())
    observed = panes.send('st-eph-review-000000', body())
    assert observed.pane == 'st-eph-review-000000'
    assert [c[-1] for c in keys(calls) if '-l' not in c] == ['Enter']


def test_failed_job_keeps_its_last_screen_owner_only(tmp_path, capsys):
    (tmp_path / 'ephemeral').mkdir()
    seen = {}

    class Panes:
        def capture(self, session, **kw):
            seen.update(kw, session=session)
            return 'last screen fixture'

    path = cli._spawn_keep_pane(types.SimpleNamespace(root=tmp_path), Panes(),
                                'st-eph-x', 'eph-x')
    assert path == tmp_path / 'ephemeral' / 'eph-x.pane.txt'
    assert path.read_text() == 'last screen fixture'
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert seen['attrs'] and seen['history'] == 200 and seen['session'] == 'st-eph-x'


def test_unreadable_pane_never_blocks_teardown(tmp_path):
    class Panes:
        def capture(self, *_a, **_kw):
            raise OSError('gone')

    assert cli._spawn_keep_pane(types.SimpleNamespace(root=tmp_path), Panes(),
                                's', 'n') is None
