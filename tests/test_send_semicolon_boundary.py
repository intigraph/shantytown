r"""tmux eats a TRAILING `;` from a send-keys argument — aegis-hni.

tmux parses an argument ending in `;` as a command separator, `-l --` or not.
Measured on tmux 3.6: `send-keys -l -- "A;"` types `A`; a mid-argument `;`
survives. Chunking splits at a fixed width, so a body whose boundary fell right
after a `;` (bobbin#259's merge prompt, "request-changes;") arrived without it.

The fake below types what REAL tmux would: it drops one trailing `;` (turning a
trailing `\;` into `;`) from each literal, and decodes `-H` hex keys. Against
the unguarded chunker these tests are red.
"""
from __future__ import annotations

from shantytown import tmux as tmux_mod


class _FakeTmux:
    def __init__(self):
        self.typed = []

    def __call__(self, argv, **kw):
        if "send-keys" in argv:
            if "-l" in argv:
                arg = argv[-1]
                if arg.endswith("\\;"):
                    arg = arg[:-2] + ";"
                elif arg.endswith(";"):
                    arg = arg[:-1]
                self.typed.append(arg)
            elif "-H" in argv:
                hexes = argv[argv.index("-H") + 1:]
                self.typed.append(bytes(int(h, 16) for h in hexes).decode())

        class _R:
            returncode = 0
            stdout = ""
        return _R()

    def text(self):
        return "".join(self.typed)


def _send(monkeypatch, text):
    fake = _FakeTmux()
    monkeypatch.setattr(tmux_mod.subprocess, "run", fake)
    monkeypatch.setattr(tmux_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(tmux_mod, "_journal_send", lambda *_a: None)
    tmux_mod.Tmux().send("some-pane", text)
    return fake


def test_a_chunk_boundary_right_after_a_semicolon_arrives_byte_identical(monkeypatch):
    head = "y" * (tmux_mod._SEND_CHUNK - len("request-changes;"))
    body = head + "request-changes;" + " and, unless Quipu's review policy for"
    assert body[tmux_mod._SEND_CHUNK - 1] == ";", "fixture missed the boundary"
    assert _send(monkeypatch, body).text() == body


def test_a_body_ending_in_semicolons_arrives_intact(monkeypatch):
    for body in ("done;", ";", ";;;", "path\\;", "a;b;"):
        assert _send(monkeypatch, body).text() == body, body


def test_the_fake_eats_a_trailing_semicolon_like_tmux(monkeypatch):
    """The check must be able to fail: an unguarded `-l` of "A;" types "A"."""
    fake = _FakeTmux()
    fake(["tmux", "send-keys", "-t", "p", "-l", "--", "A;"])
    fake(["tmux", "send-keys", "-t", "p", "-l", "--", "x;y"])
    assert fake.text() == "Ax;y"


def test_no_literal_write_ends_in_a_semicolon(monkeypatch):
    body = (("z" * (tmux_mod._SEND_CHUNK - 1)) + ";") * 3
    calls = []
    real = _FakeTmux()

    def rec(argv, **kw):
        calls.append(list(argv))
        return real(argv, **kw)
    monkeypatch.setattr(tmux_mod.subprocess, "run", rec)
    monkeypatch.setattr(tmux_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(tmux_mod, "_journal_send", lambda *_a: None)
    tmux_mod.Tmux().send("some-pane", body)
    lits = [c[-1] for c in calls if "send-keys" in c and "-l" in c]
    assert lits and not any(x.endswith(";") for x in lits)
    assert max(len(x) for x in lits) <= tmux_mod._SEND_CHUNK
    assert real.text() == body
