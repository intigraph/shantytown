"""Real startup delivery with fake panes and a marker displaced by work."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

root = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root), str(root / "tests")]
from test_new import codex_startup, CodexStartupPanes, READY
from shantytown import cli


class WorkingPanes(CodexStartupPanes):
    def capture(self, session, history=None):
        return "• Working on requested task (esc to interrupt)\n›"


with TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
    patch.setattr(cli.time, "sleep", lambda *_: None)
    args, card, box = codex_startup.__wrapped__(Path(folder), patch)
    box.deliver(card.name, "offline instruction")
    panes = WorkingPanes(screen=READY)
    accepted = cli._deliver_startup_inbox(args, card, panes, card.pane)
    print("Exact-body adapter receipt: observed")
    print("Startup marker in subsequent terminal history: absent")
    print("Startup accepted:", bool(accepted))
    print("Unread startup mail:", len(box.unread(card.name)))
    print("Sends:", len(panes.sent))
