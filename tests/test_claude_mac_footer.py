"""Quoted Claude 2.1.285 footer from the reported Mac idle pane.

These are reconstructed fixtures, not a fresh Mac capture. The original token
count exceeds the default cycle threshold, so its honest verdict is saturated.
"""
import pytest

from shantytown import cli, triage
from shantytown.runtime import ClaudeRuntime
from test_crew_work import _Args, _Panes, _roster


FOOTER = (
    "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents\n"
    "                                        ✔ Update installed · Restart to update\n"
    "                                        new task? /clear to save 678.8k tokens\n"
    "                                                                           /rc\n"
)


def verdict(screen, **kwargs):
    runtime = ClaudeRuntime.__new__(ClaudeRuntime)
    return triage.work_state(
        screen, runtime.shows_ready_ui(triage.strip_attrs(screen)), **kwargs)


@pytest.mark.parametrize("footer", [
    FOOTER,
    FOOTER.replace("678.8k", "78.8k"),
    FOOTER.replace("                                        ✔ Update installed · Restart to update\n", ""),
    FOOTER.replace("                                                                           /rc\n", ""),
])
@pytest.mark.parametrize("colored,padding", [(False, ""), (True, "\n" * 12)])
def test_extra_footer_lines_preserve_idle_and_active_controls(footer, colored, padding):
    if colored:
        footer = "\n".join(
            " ".join(f"\x1b[2m{word}\x1b[0m" for word in line.split(" "))
            for line in footer.splitlines()) + "\n"
    empty = "❯ \n" + footer + padding
    assert verdict(empty, limit_k=1000) == triage.IDLE
    typed = "\x1b[32m❯\x1b[0m pending input\n" + footer + padding
    assert verdict(typed, limit_k=1000) == triage.QUEUED
    assert verdict("Thinking… (esc to interrupt)\n" + empty) == triage.BUSY
    # Missing attributes never prove that text is a dim placeholder.
    assert verdict("❯ pending input\n" + footer + padding) == triage.UNSURE


def test_original_token_count_still_reports_saturation():
    assert verdict("❯ \n" + FOOTER) == triage.SATURATED


def test_unrecognised_footer_stays_unknown():
    assert verdict("❯ \nnew unrecognised footer\n") == triage.UNSURE


def test_crew_renders_low_context_mac_fixture_idle(tmp_path, monkeypatch, capsys):
    root = _roster(tmp_path, {"fixture": "p0"})
    panes = _Panes({"p0": "❯ \n" + FOOTER.replace("678.8k", "78.8k")})
    monkeypatch.setattr(cli, "Tmux", lambda *_a, **_kw: panes)
    assert cli._cmd_crew(_Args(root)) == cli.OK
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.split()[:1] == ["fixture"])
    assert "idle" in row.split()
    assert "1 free: fixture" in out
    assert not panes.sent
