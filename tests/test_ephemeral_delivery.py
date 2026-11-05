"""An ephemeral job is delivered when its TURN STARTS, not when its text lands
(aegis-g9w). Live on the Mac 10/28: Claude Code folded the job prompt into
`[Pasted text #1 +N lines]`, the Enter sent in the same burst was eaten, and the
job sat at turn 0 until its deadline while st counted it delivered.

The fake pane below mimics that: a write of more than 10 lines collapses to the
placeholder, and it can be told to eat Enters. Every rule gets a test that
shows it saying NO."""
from __future__ import annotations

import json

import pytest

from shantytown import cli
from shantytown import ephemeral as eph
from shantytown.tmux import NullPanes

DIM, FG, RESET = "\x1b[2m", "\x1b[38;5;246m", "\x1b[0m"
BORDER = "─" * 60


class ClaudePane:
    """Enough of a Claude Code screen to judge: transcript, spinner, composer
    frame (glyph line closed by a border), footer with a context-left figure."""

    def __init__(self, *, eat_enters=0, show_after=0, drops=False, busy=True,
                 echo=False, composer=None, crash_on_enter=False):
        self.transcript = ["Claude Code v2", ""]
        self.composer: list[str] = list(composer or [])
        self.eat_enters, self.show_after, self.drops = eat_enters, show_after, drops
        self.busy_on_submit, self.echo = busy, echo
        self.busy, self.ctx, self.typed, self.submits = False, 100, [], 0
        self.crash_on_enter, self.fg, self.shell = crash_on_enter, "claude", False
        self._pending: list[str] | None = None
        self._lag = 0

    # -- the three things deliver() touches ----------------------------------
    def type_text(self, text: str) -> None:
        self.typed.append(text)
        if self.drops:
            return
        lines = text.split("\n")
        shown = [f"[Pasted text #1 +{len(lines)} lines]"] if len(lines) > 10 else lines
        self._pending, self._lag = self.composer + shown, self.show_after

    def submit(self) -> None:
        self.submits += 1
        if self.eat_enters:
            self.eat_enters -= 1
            return
        if not self.composer:
            return
        if self.crash_on_enter:
            # The agent dies on Enter: its last frame (spinner and all) stays on
            # screen, the box is gone and the login shell's prompt is back.
            self.busy, self.ctx, self.fg, self.shell = True, 97, "zsh", True
            self.composer = []
            return
        self.transcript += ["❯ " + self.composer[0]] + ["  " + c for c in self.composer[1:]]
        if self.echo:
            self.transcript += ["  " + ln for ln in self.typed[-1].split("\n")]
        self.composer = []
        if self.busy_on_submit:
            self.busy, self.ctx = True, 97

    def capture(self) -> str:
        if self._pending is not None:
            if self._lag:
                self._lag -= 1
            else:
                self.composer, self._pending = self._pending, None
        rows = list(self.transcript)
        if self.busy:
            rows += ["✶ Roosting… (2s · thinking)"]
        if self.shell:
            return "\n".join(rows + ["", "stiwi@mac eph-task-abc123 % "])
        rows += ["", BORDER]
        if self.composer:
            rows += [f"{FG}❯\xa0\x1b[39m{self.composer[0]}"]
            rows += ["  " + c for c in self.composer[1:]]
        else:
            rows += [f"{FG}❯\xa0{DIM}Try \"how does it work?\"{RESET}"]
        rows += [BORDER, f"  [5.5] {self.ctx}% left | ws", "  auto mode on", "", ""]
        return "\n".join(rows)


def _job(n_lines=40) -> str:
    body = [f"line {i}: do the job's acceptance criteria." for i in range(n_lines)]
    return "\n".join(body + ["", "ST-STARTUP-ANCHOR-COMPLETE:eph-task-abc123:00ff"])


def _deliver(pane, text, **kw):
    return eph.deliver(text, type_text=pane.type_text, submit=pane.submit,
                       capture=pane.capture, alive=lambda: pane.fg == "claude",
                       sleep=lambda s: None, **kw)


def test_a_collapsed_paste_is_seen_then_submitted_with_its_own_enter():
    pane = ClaudePane(show_after=3)
    ok, why = _deliver(pane, _job())
    assert ok, why
    assert pane.submits == 1 and pane.busy


def test_the_eaten_enter_of_the_live_bug_is_retried_until_the_turn_starts():
    """The 10/28 shape: the first Enter is swallowed by the paste. The old path
    stopped there and called it delivered; this one sees no turn and presses
    Enter again, because the box still holds only the job."""
    pane = ClaudePane(eat_enters=1)
    ok, why = _deliver(pane, _job())
    assert ok and pane.submits == 2, why


def test_no_turn_after_the_bounded_retries_is_a_launch_failure():
    pane = ClaudePane(eat_enters=99)
    ok, why = _deliver(pane, _job(), attempts=3)
    assert not ok and pane.submits == 3
    assert "3 Enters" in why


def test_foreign_text_in_the_box_is_refused_nothing_typed_no_enter():
    pane = ClaudePane(composer=["half-typed operator note"])
    ok, why = _deliver(pane, _job())
    assert not ok and pane.typed == [] and pane.submits == 0
    assert "did not put there" in why


def test_a_job_that_never_shows_in_the_box_gets_no_enter():
    pane = ClaudePane(drops=True)
    ok, why = _deliver(pane, _job(), show_looks=4)
    assert not ok and pane.submits == 0 and "never showed" in why


def test_a_transient_foreign_frame_waits_but_a_lasting_one_gets_no_enter():
    """A redraw mid-type can show a frame that is not only ours (seen live once,
    right after a turn). Wait it out; if it lasts, refuse with no Enter."""
    pane = ClaudePane()
    real_capture, frames = pane.capture, {"n": 0}

    def capture_with_one_odd_frame():
        frames["n"] += 1
        screen = real_capture()
        return screen.replace("line 0:", "ghost suggestion line 0:") if frames["n"] == 2 else screen
    pane.capture = capture_with_one_odd_frame
    ok, why = _deliver(pane, _job(n_lines=5))
    assert ok and pane.submits == 1, why

    pane = ClaudePane()
    real = pane.type_text
    pane.type_text = lambda t: (real(t), setattr(pane, "_pending", ["not ours at all"]))
    ok, why = _deliver(pane, _job(), show_looks=4)
    assert not ok and pane.submits == 0 and "not the job's" in why


def test_text_appearing_beside_the_job_stops_the_retries():
    """Someone types into the box between Enters: st must not press Enter on
    text that is not the job's."""
    pane = ClaudePane(eat_enters=99)
    real_submit = pane.submit

    def submit_then_human_types():
        real_submit()
        pane.composer = pane.composer + ["and also rm the worktree"]
    pane.submit = submit_then_human_types
    ok, why = _deliver(pane, _job(), attempts=3)
    assert not ok and pane.submits == 1 and "no longer holds just the job" in why


def test_a_cleared_box_without_any_sign_of_a_turn_is_not_started():
    """The box letting go is not enough: a busy marker, a spinner, a context
    drop or the job echoed into the transcript must show."""
    pane = ClaudePane(busy=False)
    ok, why = _deliver(pane, _job(), attempts=2, start_looks=2)
    assert not ok and pane.submits == 1


def test_an_echoed_job_is_not_a_sign_of_work():
    """The job echoed into the transcript proves a submit, not a working turn."""
    pane = ClaudePane(busy=False, echo=True)
    ok, why = _deliver(pane, _job(n_lines=5), attempts=2, start_looks=2)
    assert not ok and pane.submits == 1, why


def test_an_agent_that_drops_to_the_shell_on_enter_is_a_launch_failure():
    """#411 review: the crash leaves a busy frame and a context drop on screen,
    and the box is gone. Counting that as started idles the job until its
    deadline. The process is the shell now: launch failed, no second Enter."""
    pane = ClaudePane(crash_on_enter=True)
    ok, why = _deliver(pane, _job())
    assert not ok and pane.submits == 1 and "exited to the shell" in why


def test_an_unreadable_foreground_never_counts_as_started():
    pane = ClaudePane()
    ok, why = eph.deliver(_job(), type_text=pane.type_text, submit=pane.submit,
                          capture=pane.capture, alive=lambda: None,
                          sleep=lambda s: None, attempts=1, start_looks=2)
    assert not ok and pane.busy


def test_box_state_reads_the_placeholder_as_empty_and_the_token_as_ours():
    pane = ClaudePane()
    assert eph.box_state(pane.capture(), _job()) == eph.EMPTY
    pane.composer = ["[Pasted text #1 +41 lines]"]
    assert eph.box_state(pane.capture(), _job()) == eph.OURS
    pane.composer = ["[Pasted text #1 +41 lines] plus something else"]
    assert eph.box_state(pane.capture(), _job()) == eph.FOREIGN
    assert eph.box_state("no frame here\n", _job()) == eph.UNSEEN


def test_the_claude_paste_placeholder_now_reads_as_stranded():
    from shantytown.runtime import input_stranded
    assert input_stranded("❯ [Pasted text #1 +41 lines]\n" + BORDER + "\n")


# --- end to end through st agent spawn ---------------------------------------

class _SpawnPane(NullPanes):
    """NullPanes for the session lifecycle; a ClaudePane for the screen."""

    def __init__(self, claude):
        super().__init__(live=set())
        self.claude = claude

    def capture(self, pane, history=0, attrs=False, *, timeout=None):
        return self.claude.capture()

    def type_text(self, pane, text):
        self.claude.type_text(text)

    def submit(self, pane):
        self.claude.submit()

    def foreground(self, pane):
        return self.claude.fg


@pytest.fixture
def spawn(tmp_path, monkeypatch):
    root = tmp_path / ".shanty"
    (root / "crew").mkdir(parents=True)
    (root / "crew" / "boss.json").write_text(json.dumps(
        {"role": "administrator", "pane": "st-boss", "dangerous": True}))
    (root / "shantytown.toml").write_text("[ephemeral]\nmax_agents = 1\nunattended = false\n")
    monkeypatch.setattr(eph, "LOOK_S", 0.0)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    def run(claude):
        panes = _SpawnPane(claude)
        monkeypatch.setattr(cli, "_panes", lambda a: panes)

        def fake_launch(a, card, panes_, runtime, **kw):
            panes.new_session(card.pane)
            a._startup_delivered = bool(cli._deliver_startup_inbox(a, card, panes, card.pane))
            return cli.CANNOT_TELL
        monkeypatch.setattr(cli, "_launch", fake_launch)
        monkeypatch.setattr(cli, "_runtime", lambda a, p: None)
        monkeypatch.setattr(eph, "deliver", _fast(eph.deliver))
        monkeypatch.delenv("SHANTY_AGENT", raising=False)
        monkeypatch.setenv("GT_ROOT", str(tmp_path / "gt"))
        rc = cli.main(["--root", str(root), "agent", "spawn", "--ephemeral", "--job",
                       "task", "--item", "it-1"])
        (rec,) = eph.records(root)
        return rc, rec, panes
    return run


def _fast(real):
    def deliver(text, **kw):
        kw.setdefault("sleep", lambda s: None)
        return real(text, **kw)
    return deliver


def test_spawn_goes_live_only_once_the_job_turn_started(spawn):
    claude = ClaudePane(eat_enters=1)
    rc, rec, _panes = spawn(claude)
    assert rc == cli.OK and rec["state"] == eph.LIVE
    assert claude.submits == 2 and "[Pasted text #1" in "\n".join(claude.transcript)


def test_spawn_ends_a_job_whose_turn_never_started_as_launch_failed(spawn):
    claude = ClaudePane(eat_enters=99)
    rc, rec, panes = spawn(claude)
    assert rc == cli.CANNOT_TELL
    assert rec["state"] == eph.DONE and rec["result"]["cause"] == "launch failed"
    assert "no turn started" in rec["result"]["summary"]
    assert claude.submits == eph.SUBMIT_ATTEMPTS
    assert not panes.exists(f"st-{rec['name']}")


def test_spawn_ends_a_job_whose_agent_crashed_on_enter(spawn):
    claude = ClaudePane(crash_on_enter=True)
    rc, rec, _panes = spawn(claude)
    assert rc == cli.CANNOT_TELL and rec["result"]["cause"] == "launch failed"
    assert "exited to the shell" in rec["result"]["summary"]
