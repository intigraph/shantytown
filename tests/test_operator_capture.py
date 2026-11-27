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


def capture(root, writer, text=TEXT, at=AT, channel="inbox"):
    return oc.capture(root, text, recipient="sattler", session="sess-1",
                      channel=channel, received_at=at, writer=writer)


def test_one_message_one_node_verbatim_with_real_utc(tmp_path):
    w = Writer()
    record = capture(tmp_path, w)
    assert w.calls == [(record.key, "message")]
    assert record.text == TEXT
    assert record.received_at == "2026-11-27T04:45:12Z"
    assert (record.recipient, record.session, record.channel) == ("sattler", "sess-1", "inbox")
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


def test_redelivery_with_a_later_clock_writes_nothing(tmp_path):
    """Keying on the capture instant alone deduped only within one second."""
    w = Writer()
    first = capture(tmp_path, w)
    for later in (timedelta(seconds=1), timedelta(minutes=5), oc.REDELIVERY_WINDOW):
        assert capture(tmp_path, w, at=AT + later) is None, later
    assert w.calls == [(first.key, "message")]
    assert len(oc.records(tmp_path)) == 1


def test_same_text_after_the_window_is_a_new_message(tmp_path):
    w = Writer()
    capture(tmp_path, w)
    capture(tmp_path, w, at=AT + oc.REDELIVERY_WINDOW + timedelta(seconds=1))
    assert len(oc.records(tmp_path)) == 2


def test_same_text_to_another_recipient_is_a_new_message(tmp_path):
    w = Writer()
    capture(tmp_path, w)
    oc.capture(tmp_path, TEXT, recipient="ellie", session="sess-1",
               channel="inbox", received_at=AT + timedelta(seconds=5), writer=w)
    assert sorted(r.recipient for r in oc.records(tmp_path)) == ["ellie", "sattler"]


@pytest.mark.parametrize("later", [timedelta(0), timedelta(seconds=0.4), timedelta(seconds=3)])
def test_a_repeated_pane_prompt_is_two_records(tmp_path, later):
    """A prompt hook is never redelivered: "go" typed twice was typed twice."""
    w, env = Writer(), {"SHANTY_AGENT": "sattler"}
    for when in (AT, AT + later):
        assert oc.hook(tmp_path, json.dumps({"prompt": "go", "session_id": "s1"}),
                       env=env, now=when, writer=w) is not None
    found = oc.records(tmp_path)
    assert [r.text for r in found] == ["go", "go"]
    assert len({r.key for r in found}) == 2 and len(w.calls) == 2


def test_hook_without_an_agent_identity_still_spools(tmp_path, capsys):
    record = oc.hook(tmp_path, json.dumps({"prompt": TEXT}), env={}, now=AT, writer=Writer())
    assert record.text == TEXT and record.recipient == ""
    assert "a:recipient" not in oc.turtle(ONTO, record, "message")
    assert "UNKNOWN" in capsys.readouterr().err


def test_a_corrupt_spool_record_is_skipped_and_reported_unknown(tmp_path, monkeypatch, capsys):
    from shantytown.cli import CANNOT_TELL
    good = capture(tmp_path, Writer())
    bad = oc.spool_dir(tmp_path) / "om-20261127T000000Z-0000000000000000.json"
    bad.write_text("{not json")
    (oc.spool_dir(tmp_path) / "om-20261127T000001Z-0000000000000001.json").write_text('{"x": 1}')
    seen = []
    assert [r.key for r in oc.records(tmp_path, seen)] == [good.key] and len(seen) == 2
    assert any("UNKNOWN (2)" in line for line in oc.notices(tmp_path, now=AT))
    monkeypatch.setattr(oc, "_default_writer", lambda root: Writer())
    assert _directive(tmp_path, "list") == 0
    assert "UNKNOWN" in capsys.readouterr().out
    assert _directive(tmp_path, "flush") == CANNOT_TELL     # cannot vouch for the corrupt one
    assert bad.exists()                                      # never deleted


@pytest.mark.parametrize("name", ["aegis-x1.", "x.", "-x", "X1"])
def test_a_name_that_would_break_turtle_is_refused(tmp_path, name):
    record = capture(tmp_path, Writer())
    with pytest.raises(oc.CaptureRefused):
        oc.track(tmp_path, record.key, name, writer=Writer())
    with pytest.raises(oc.CaptureRefused):
        oc.capture(tmp_path, "other text", recipient=name, session="", channel="inbox",
                   received_at=AT)
    assert oc.load(tmp_path, record.key).tracked_by == []


def test_flush_keeps_a_mark_that_lands_while_it_writes(tmp_path):
    """flush used to save the copy it loaded, overwriting directive=True."""
    record = capture(tmp_path, Writer(fail=1))
    marked = []

    def writer(rec, statement):
        if not marked:   # the administrator marks while the node write is in flight
            marked.append(oc._update(tmp_path, rec.key, lambda r: setattr(r, "directive", True)))

    oc.flush(tmp_path, writer=writer)
    after = oc.load(tmp_path, record.key)
    assert after.directive and after.written == ["message"]
    assert after.owed() == ["directive"]


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
    # 7, not the default 30: a test at the default cannot see the knob ignored.
    monkeypatch.setenv(oc.TRACK_MINUTES_KEY, "7")
    assert oc.TRACK_MINUTES != 7
    w = Writer()
    record = capture(tmp_path, w)
    assert any("TO REVIEW" in line for line in oc.notices(tmp_path, now=AT))
    oc.mark(tmp_path, record.key, writer=w)
    assert not any("UNTRACKED" in l for l in oc.notices(tmp_path, now=AT + timedelta(minutes=6)))
    late = oc.notices(tmp_path, now=AT + timedelta(minutes=8))
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


def test_an_invalid_recipient_name_is_refused(tmp_path):
    with pytest.raises(oc.CaptureRefused):
        oc.capture(tmp_path, TEXT, recipient="Not A Name", session="", channel="inbox",
                   received_at=AT)


def test_hook_is_administrator_only():
    assert runtime.operator_capture_hooks("worker", "/r") == []
    hooks = runtime.operator_capture_hooks("administrator", "/r")
    assert "shantytown.operator_capture" in hooks[0]["hooks"][0]["command"]
    prompt = runtime.claude_settings_for_role("administrator", "/r")["hooks"]["UserPromptSubmit"]
    assert any("operator_capture" in h["command"] for g in prompt for h in g["hooks"])


def test_hook_spools_and_hands_the_write_to_a_detached_flush(tmp_path, monkeypatch):
    """The prompt must not wait on Quipu: no writer runs inside the hook."""
    inline = Writer()
    monkeypatch.setattr(oc, "_default_writer", lambda root: inline)
    spawned = []
    got = oc.hook(tmp_path, json.dumps({"prompt": TEXT}), env={"SHANTY_AGENT": "sattler"},
                  now=AT, spawn=lambda root, key: spawned.append(key))
    assert spawned == [got.key] and inline.calls == []
    assert oc.load(tmp_path, got.key).owed() == ["message"]


def test_detached_flush_entry_point_delivers_one_record(tmp_path, monkeypatch):
    record = capture(tmp_path, Writer(fail=1))
    w = Writer()
    monkeypatch.setattr(oc, "_default_writer", lambda root: w)
    assert oc.main(["--root", str(tmp_path), "--flush", record.key]) == 0
    assert w.calls == [(record.key, "message")]
    assert oc.load(tmp_path, record.key).owed() == []


# --- the CLI wiring: deleting any of these call sites must fail a test -------

class _NoPanes:
    def exists(self, pane):
        return False


def _cli_store(tmp_path, **card):
    crew = tmp_path / "crew"
    crew.mkdir(parents=True, exist_ok=True)
    # A pane name nothing runs: the routine send ends "pane is not there".
    (crew / "dearing.json").write_text(json.dumps(
        {"role": "lead", "reports_to": "sattler", "pane": "st-test-no-such-pane", **card}))
    return tmp_path


def _inbox(monkeypatch, root, *, operator, sender="stiwi"):
    from shantytown import cli
    monkeypatch.setattr(cli, "_panes", lambda a: _NoPanes())
    spawned = []
    monkeypatch.setattr(oc, "spawn_flush", lambda r, key: spawned.append(key))
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("SHANTY_AGENT", sender)
    if operator:
        monkeypatch.setenv(oc.OPERATOR_KEY, operator)
    rc = cli.main(["--root", str(root), "inbox", "dearing", "ship", "it"])
    return rc, spawned


def test_st_inbox_from_the_operator_is_captured_and_flushed_detached(tmp_path, monkeypatch):
    root = _cli_store(tmp_path)
    rc, spawned = _inbox(monkeypatch, root, operator="stiwi")
    found = oc.records(root)
    assert [(r.text, r.recipient, r.channel) for r in found] == [("ship it", "dearing", "inbox")]
    assert spawned == [found[0].key]
    assert rc != 0          # the pane is absent; capture still happened first


@pytest.mark.parametrize("operator", [None, "someone-else"])
def test_st_inbox_without_a_matching_operator_captures_nothing(tmp_path, monkeypatch, operator):
    root = _cli_store(tmp_path)
    _inbox(monkeypatch, root, operator=operator)
    assert not oc.spool_dir(root).exists() or oc.records(root) == []


def test_st_inbox_relayed_off_host_is_captured_by_the_far_side_only(tmp_path, monkeypatch):
    root = _cli_store(tmp_path, host="far-host")
    monkeypatch.setenv("SHANTY_HOST", "this-host")
    _inbox(monkeypatch, root, operator="stiwi")
    assert not oc.spool_dir(root).exists() or oc.records(root) == []


def _directive(tmp_path, *argv):
    from shantytown import cli
    return cli.main(["--root", str(tmp_path), "work", "directive", *argv])


def test_st_work_directive_exit_codes(tmp_path, monkeypatch, capsys):
    from shantytown.cli import CANNOT_TELL, OK, REFUSED
    record = capture(tmp_path, Writer())
    assert _directive(tmp_path, "list") == OK
    assert record.key in capsys.readouterr().out
    assert _directive(tmp_path, "mark") == REFUSED                 # missing key
    assert _directive(tmp_path, "mark", "om-nope") == REFUSED      # not a key
    assert _directive(tmp_path, "track", record.key, "bad.") == REFUSED
    monkeypatch.setattr(oc, "_default_writer", lambda root: Writer(fail=99))
    assert _directive(tmp_path, "mark", record.key) == CANNOT_TELL  # spooled, owed
    assert oc.load(tmp_path, record.key).directive
    assert _directive(tmp_path, "flush") == CANNOT_TELL
    w = Writer()
    monkeypatch.setattr(oc, "_default_writer", lambda root: w)
    assert _directive(tmp_path, "flush") == OK
    assert w.calls == [(record.key, "directive")]
    assert _directive(tmp_path, "track", record.key, SEED) == OK
    assert oc.load(tmp_path, record.key).tracked_by == [SEED]


def test_st_task_directive_links_the_new_seed(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    record = capture(tmp_path, Writer())
    w = Writer()
    monkeypatch.setattr(oc, "_default_writer", lambda root: w)
    rc = cli.main(["--root", str(tmp_path), "task", "record the directive",
                   "--directive", record.key])
    out = capsys.readouterr()
    linked = oc.load(tmp_path, record.key)
    assert linked.directive and len(linked.tracked_by) == 1, (rc, out)
    seed = linked.tracked_by[0]
    assert seed in out.out and w.calls[-1] == (record.key, f"tracked:{seed}")


def test_st_task_directive_refuses_an_unlinkable_ref_before_creating(tmp_path, monkeypatch, capsys):
    from shantytown import cli
    created = []
    monkeypatch.setattr(cli, "_tracker", lambda a: created.append(1) or (_ for _ in ()).throw(AssertionError))
    rc = cli.main(["--root", str(tmp_path), "task", "x",
                   "--directive", "http://aegis.gastown.local/ontology/stiwi-directive-hand-minted"])
    assert rc == cli.REFUSED and not created
    assert "not an operator message key" in capsys.readouterr().err


def test_st_task_directive_link_refused_after_create_exits_refused(tmp_path, monkeypatch):
    from shantytown import cli
    record = capture(tmp_path, Writer())
    monkeypatch.setattr(oc, "track", lambda *a, **k: (_ for _ in ()).throw(oc.CaptureRefused("no")))
    rc = cli.main(["--root", str(tmp_path), "task", "x", "--directive", record.key])
    assert rc == cli.REFUSED


def test_st_task_directive_link_still_owed_exits_cannot_tell(tmp_path, monkeypatch):
    from shantytown import cli
    record = capture(tmp_path, Writer())
    monkeypatch.setattr(oc, "_default_writer", lambda root: Writer(fail=99))
    rc = cli.main(["--root", str(tmp_path), "task", "x", "--directive", record.key])
    assert rc == cli.CANNOT_TELL
    assert oc.load(tmp_path, record.key).tracked_by
