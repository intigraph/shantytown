"""aegis-zxor: the haul Stop hook reads its stdin payload ONCE.

On vati (overdue_spec_changes on) the spec-boundary read drained the hook's
stdin, then stop_advice json-loaded an empty stream and wrote a NULL session
identity into context_budget on every such Stop, so soft self-cycles failed
"incomplete hook session identity" (wu, 2026-11-12).
"""
import io
import json
import os
from types import SimpleNamespace

from shantytown import config, spec_boundary, stop_event, stop_policy


class Stdin(io.StringIO):
    """A pipe-like stdin: not a tty, has a real fd for select/os.read."""

    def __init__(self, text):
        super().__init__(text)
        self._r, w = os.pipe()
        os.write(w, text.encode())
        os.close(w)

    def isatty(self):
        return False

    def fileno(self):
        return self._r

    def read(self, *args):
        return os.read(self._r, 1 << 20).decode()


def test_spec_boundary_and_stop_advice_see_the_same_identity(tmp_path, monkeypatch):
    payload = {"session_id": "s-1", "transcript_path": "/t/s-1.jsonl",
               "hook_event_name": "Stop"}
    monkeypatch.setattr("sys.stdin", Stdin(json.dumps(payload)))
    monkeypatch.setenv("SHANTY_AGENT", "wu")
    monkeypatch.setattr(stop_event, "_stop_identity", lambda *a: "wu")
    monkeypatch.setattr(stop_event, "Tmux", lambda **k: None)
    monkeypatch.setattr(stop_event, "declared_socket", lambda root: None)
    monkeypatch.setattr(stop_event, "_ceiling_took_the_stop", lambda *a: (False,))
    monkeypatch.setattr(config, "load_or_default", lambda root: (
        SimpleNamespace(overdue_enabled=True, overdue_spec_changes=True), None))
    seen = {}
    monkeypatch.setattr(spec_boundary, "at_boundary",
                        lambda root, me, reg, *, hook=None: seen.setdefault("boundary", hook) and None)

    def advice(root, card, payload=None):
        if payload is None:  # the pre-fix path: read the (possibly drained) stream
            try:
                payload = json.load(__import__("sys").stdin)
            except ValueError:
                payload = {}
        seen["advice"] = payload
        return True
    monkeypatch.setattr(stop_policy, "stop_advice", advice)
    monkeypatch.setattr(stop_event.FilesRegistry, "get", lambda self, name: SimpleNamespace(name=name))
    assert stop_event.main(["haul", "--root", str(tmp_path)]) == 0
    assert seen["boundary"] == payload
    assert seen["advice"] == payload, "the Stop advice got an empty, drained stream"


def test_read_hook_payload_is_empty_for_a_terminal_or_garbage(monkeypatch):
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    assert stop_policy.read_hook_payload() == {}
    monkeypatch.setattr("sys.stdin", Stdin("not json"))
    assert stop_policy.read_hook_payload() == {}
    monkeypatch.setattr("sys.stdin", Stdin("[1, 2]"))
    assert stop_policy.read_hook_payload() == {}
