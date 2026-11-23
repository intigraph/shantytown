"""aegis-5x2x: wait for a fresh Codex pane's startup hooks before the first turn."""
from shantytown import cli

# The frame seen on eph-merge-ef45a2 / eph-review-40aee2 (attributes stripped).
BUSY = ("ST-STARTUP-ANCHOR-COMPLETE:eph-review-40aee2:f4ac0c2c54d16fe5\n"
        "• Working (1s • esc to interrupt) · Running hooks\n"
        "› Ask Codex to do anything\n"
        "  GPT-6.1 Terra default · ~/gt/shantytown-wt/eph-review-40aee2\n")
IDLE = ("› Ask Codex to do anything\n"
        "  GPT-6.1 Terra default · ~/gt/shantytown-wt/eph-review-40aee2\n")


class Panes:
    def __init__(self, frames):
        self.frames, self.calls = list(frames), 0

    def capture(self, session, attrs=False):
        self.calls += 1
        frame = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        if isinstance(frame, Exception):
            raise frame
        return frame


def test_waits_through_startup_hooks_then_reports_idle():
    panes, slept = Panes([BUSY, BUSY, BUSY, IDLE]), []
    assert cli._wait_codex_startup_idle(panes, "s", looks=10, sleep=slept.append)
    assert panes.calls == 4 and len(slept) == 3


def test_idle_pane_is_not_delayed():
    panes, slept = Panes([IDLE]), []
    assert cli._wait_codex_startup_idle(panes, "s", looks=10, sleep=slept.append)
    assert slept == []


def test_gives_up_after_the_bound_without_claiming_idle():
    panes, slept = Panes([BUSY]), []
    assert not cli._wait_codex_startup_idle(panes, "s", looks=5, sleep=slept.append)
    assert panes.calls == 5 and len(slept) == 4


def test_unreadable_pane_is_not_idle_proof():
    panes = Panes([OSError("gone")])
    assert not cli._wait_codex_startup_idle(panes, "s", looks=3, sleep=lambda _: None)
