"""Sanitized composer shapes from 2026-10-23 8mcb captures; no private text."""
from pathlib import Path
import pytest
from shantytown import input_box

FIXTURES = Path(__file__).parent / "fixtures" / "codex_input"

def capture(name):
    return (FIXTURES / name).read_text()

class Panes:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.frame = next(self.frames)
        self.keys = []
    def capture(self, pane, attrs=True):
        return self.frame
    def control(self, pane, key):
        self.keys.append(key)
        if key == "BSpace":
            self.frame = next(self.frames, self.frame)

@pytest.mark.parametrize("name", ["ian-before.txt", "dearing-before-full.txt"])
def test_real_multiline_typed(name):
    report = input_box.show(Panes([capture(name)]), "pane")
    assert report.verdict == input_box.TYPED
    assert "Example pending message\n  continuation" in report.text
    assert "GPT-" not in report.text

def test_empty_placeholder():
    assert input_box.show(Panes([capture("ian-after.txt")]), "p").verdict == input_box.EMPTY

def test_dim_suggestion():
    screen = "\x1b[1m›\x1b[0m \x1b[2mImprove documentation\x1b[0m\n\n  GPT-6.1-Sol default · ~/project · Task\n ? for shortcuts"
    assert input_box.show(Panes([screen]), "p").verdict == input_box.GHOST

def test_multiline_clear_proves_placeholder():
    p = Panes([capture("dearing-before-full.txt"), capture("ian-before.txt"), capture("ian-after.txt")])
    result = input_box.clear(p, "p")
    assert result.verdict == input_box.EMPTY
    assert p.keys == ["C-e", "C-u", "BSpace"] * 2
    assert result.changed

@pytest.mark.parametrize("busy", ["• Working (12s • esc to interrupt)\n", ""])
def test_busy_refuses_without_keys(busy):
    screen = busy + capture("ian-before.txt")
    if not busy:
        screen += "tab to queue message\n"
    p = Panes([screen])
    result = input_box.clear(p, "p")
    assert "REFUSED" in result.detail
    assert p.keys == []

def test_old_transcript_without_footer_is_not_codex():
    assert input_box._codex_box("› old transcript\nordinary output") is None


def test_busy_empty_refuses():
    p = Panes(["• Working (2s • esc to interrupt)\n" + capture("ian-after.txt")])
    assert "REFUSED" in input_box.clear(p, "p").detail
    assert not p.keys

def test_no_repaint_is_unknown_not_success(monkeypatch):
    monkeypatch.setattr(input_box, "_SETTLE_S", 0)
    p = Panes([capture("ian-before.txt")])
    result = input_box.clear(p, "p")
    assert not result.changed
    assert "UNKNOWN" in result.detail
    assert result.verdict == input_box.TYPED

def test_becomes_busy_between_lines_stops():
    busy = "• Working (1s • esc to interrupt)\n" + capture("ian-before.txt")
    p = Panes([capture("dearing-before-full.txt"), busy])
    p.frame = p.frame.replace("Example pending message", "Different first frame")
    result = input_box.clear(p, "p")
    assert "REFUSED" in result.detail
    assert p.keys == ["C-e", "C-u", "BSpace"]

def test_long_composer_above_old_tail():
    screen = "› typed\n" + "  wrapped text\n" * 15 + "\n  GPT-6.1-Sol default · ~/project · Task\n ? for shortcuts"
    result = input_box.show(Panes([screen]), "p")
    assert result.verdict == input_box.TYPED
    assert result.text.count("wrapped text") == 15


def test_foreign_text_stops_further_deletion():
    foreign = capture("ian-before.txt").replace("Example pending message", "Foreign pending message")
    p = Panes([capture("dearing-before-full.txt"), foreign])
    result = input_box.clear(p, "p")
    assert "preserving remaining text" in result.detail
    assert result.verdict == input_box.TYPED
    assert p.keys == ["C-e", "C-u", "BSpace"]


def test_terminal_padding_does_not_hide_composer():
    screen = capture("ian-before.txt") + "\n" * 20
    assert input_box.show(Panes([screen]), "p").verdict == input_box.TYPED


@pytest.mark.parametrize("box", ["typed", "empty", "ghost"])
@pytest.mark.parametrize("activity", ["working", "queue"])
def test_busy_dismiss_never_sends_escape(box, activity):
    if box == "ghost":
        screen = "\x1b[1m›\x1b[0m \x1b[2mImprove documentation\x1b[0m\n\n  GPT-6.1-Sol default · ~/project · Task\n ? for shortcuts"
    else:
        screen = capture("ian-before.txt" if box == "typed" else "ian-after.txt")
    screen = ("• Working (12s • esc to interrupt)\n" + screen if activity == "working"
              else screen + "tab to queue message\n")
    p = Panes([screen])
    result = input_box.dismiss(p, "p")
    assert result.verdict == input_box.BUSY
    assert "REFUSED" in result.detail
    assert p.keys == []


def test_cli_busy_dismiss_exits_refused(monkeypatch):
    from types import SimpleNamespace
    from shantytown import cli, runtime
    p = Panes(["• Working (12s • esc to interrupt)\n" + capture("ian-after.txt")])
    p.exists = lambda pane: True
    monkeypatch.setattr(cli, "_panes", lambda args: p)
    monkeypatch.setattr(cli, "_registry", lambda args: SimpleNamespace(get=lambda agent: SimpleNamespace(pane="p")))
    monkeypatch.setattr(cli, "_runtime", lambda *args: None)
    monkeypatch.setattr(runtime, "asks_a_question", lambda *args: False)
    args = SimpleNamespace(agent="example", clear=False, dismiss=True)
    assert cli._cmd_input(args) == cli.REFUSED
    assert p.keys == []


@pytest.mark.parametrize("screen", ["ordinary output", "❯ unclassified text"])
def test_dismiss_unverified_surface_refuses_without_keys(screen):
    p = Panes([screen])
    assert "REFUSED" in input_box.dismiss(p, "p").detail
    assert p.keys == []
