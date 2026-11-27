"""aegis-za4f.20: st captures every operator message verbatim, exactly once."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from shantytown import operator_capture as oc
from shantytown import runtime

AT = datetime(2026, 11, 27, 4, 45, 12, 345000, tzinfo=timezone.utc)
TEXT = 'Ya good idea! Do that for auto directives / St is the right place fkr it too "quoted"\n\\ ünïcode'
ONTO = "http://aegis.gastown.local/ontology/"
SEED = "demo-seed.1"   # any seed id; a real-looking one trips the secret scanner


class Writer:
    def __init__(self, fail=0):
        self.calls, self.fail = [], fail

    def __call__(self, record, statement):
        if self.fail:
            self.fail -= 1
            raise OSError("quipu down")
        self.calls.append((record.key, statement))


def capture(root, writer, text=TEXT, at=AT):
    return oc.capture(root, text, recipient="sattler", session="sess-1",
                      channel="pane-prompt", received_at=at, writer=writer)


def test_one_message_one_node_verbatim_with_real_utc(tmp_path):
    w = Writer()
    record = capture(tmp_path, w)
    assert w.calls == [(record.key, "message")]
    assert record.text == TEXT
    assert record.received_at == "2026-11-27T04:45:12Z"
    assert (record.recipient, record.session, record.channel) == ("sattler", "sess-1", "pane-prompt")
    assert not record.directive and record.owed() == []
    ttl = oc.turtle(ONTO, record, "message")
    assert "a:OperatorMessage" in ttl and "a:Directive" not in ttl
    assert f'a:receivedAt "2026-11-27T04:45:12Z"^^xsd:dateTime' in ttl
    assert "a:recipient a:sattler" in ttl and 'a:sourceKind "operator-verbatim"' in ttl
    # The literal round-trips to the exact text: verbatim, not paraphrased.
    comment = ttl.split("rdfs:comment ", 1)[1].split(" ;\n", 1)[0]
    assert json.loads(comment) == TEXT


def test_redelivery_writes_nothing(tmp_path):
    w = Writer()
    first = capture(tmp_path, w)
    assert capture(tmp_path, w) is None
    assert w.calls == [(first.key, "message")]
    assert len(oc.records(tmp_path)) == 1


def test_same_text_at_another_time_is_a_new_message(tmp_path):
    w = Writer()
    capture(tmp_path, w)
    capture(tmp_path, w, at=AT + timedelta(minutes=1))
    assert len(oc.records(tmp_path)) == 2


def test_quipu_failure_spools_and_retries_idempotently(tmp_path):
    w = Writer(fail=1)
    record = capture(tmp_path, w)
    assert record.owed() == ["message"] and w.calls == []
    assert oc.records(tmp_path)[0].text == TEXT          # never lost
    assert any("SPOOLED" in line for line in oc.notices(tmp_path, now=AT))
    done, failed = oc.flush(tmp_path, writer=w)
    assert (done, failed) == (1, [])
    assert oc.flush(tmp_path, writer=w) == (0, [])        # retry again: no rewrite
    assert w.calls == [(record.key, "message")]


def test_failed_node_write_holds_back_the_link(tmp_path):
    w = Writer(fail=1)
    record = capture(tmp_path, w)
    w.fail = 5
    oc.track(tmp_path, record.key, SEED, writer=w)
    assert oc.load(tmp_path, record.key).owed() == ["message", "directive", f"tracked:{SEED}"]
    assert w.calls == []


def test_seed_link_writes_directive_and_tracked_by(tmp_path):
    w = Writer()
    record = capture(tmp_path, w)
    linked = oc.track(tmp_path, f"{ONTO}{record.key}", SEED, writer=w)
    assert linked.directive and linked.tracked_by == [SEED]
    assert w.calls[1:] == [(record.key, "directive"), (record.key, f"tracked:{SEED}")]
    assert f"a:trackedBy a:{SEED}" in oc.turtle(ONTO, linked, f"tracked:{SEED}")
    oc.track(tmp_path, record.key, SEED, writer=w)
    assert len(w.calls) == 3                               # relinking is not a second edge


def test_untracked_directive_raises_notice_only_after_window(tmp_path, monkeypatch):
    monkeypatch.setenv(oc.TRACK_MINUTES_KEY, "30")
    w = Writer()
    record = capture(tmp_path, w)
    assert any("TO REVIEW" in line for line in oc.notices(tmp_path, now=AT))
    oc.mark(tmp_path, record.key, writer=w)
    assert not any("UNTRACKED" in l for l in oc.notices(tmp_path, now=AT + timedelta(minutes=29)))
    late = oc.notices(tmp_path, now=AT + timedelta(minutes=31))
    assert any("UNTRACKED DIRECTIVES (1)" in l for l in late)
    assert any(record.key in l for l in late)
    oc.track(tmp_path, record.key, "aegis-x1", writer=w)
    assert oc.notices(tmp_path, now=AT + timedelta(days=1)) == []


def test_hook_captures_operator_and_skips_st_deliveries(tmp_path):
    w = Writer()
    env = {"SHANTY_AGENT": "sattler"}
    got = oc.hook(tmp_path, json.dumps({"prompt": TEXT, "session_id": "s9"}),
                  env=env, now=AT, writer=w)
    assert got.session == "s9" and got.text == TEXT
    for crew in ("[from ellie] please record this", "[from st startup] You are x"):
        assert oc.hook(tmp_path, json.dumps({"prompt": crew}), env=env, now=AT, writer=w) is None
    assert len(oc.records(tmp_path)) == 1


def test_refuses_without_a_recipient_identity(tmp_path):
    with pytest.raises(oc.CaptureRefused):
        oc.capture(tmp_path, TEXT, recipient="", session="", channel="inbox", received_at=AT)


def test_hook_is_administrator_only():
    assert runtime.operator_capture_hooks("worker", "/r") == []
    hooks = runtime.operator_capture_hooks("administrator", "/r")
    assert "shantytown.operator_capture" in hooks[0]["hooks"][0]["command"]
    prompt = runtime.claude_settings_for_role("administrator", "/r")["hooks"]["UserPromptSubmit"]
    assert any("operator_capture" in h["command"] for g in prompt for h in g["hooks"])
