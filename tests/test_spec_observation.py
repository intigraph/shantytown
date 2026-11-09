"""Private native-event controls; no live hooks, sender, spec generation, or ACK."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shantytown import spec_observation as evidence
from shantytown.answer import Answer
from shantytown.spec_boundary import consume


HOOK = {"hook_event_name": "Stop", "session_id": "session", "hook_run_id": "hook-1"}
BODY = "work-spec SPEC CHANGED v1 -> v2 (unacked)"


def emission(root, **overrides):
    return evidence.emitted(root, "owner", "codex", HOOK | overrides,
                            [{"id": "work-spec", "version": 2}], BODY)


def archive(root, wire, *, session="session", turn="turn-1", role="developer",
            kind="message", trailing=b"", content_type="input_text"):
    path = root / "archive.jsonl"
    entries = [{"type": "session_meta", "payload": {"id": session}},
               {"type": "turn_context", "payload": {"turn_id": turn}},
               {"type": "response_item", "payload": {
                   "type": kind, "role": role,
                   "content": [{"type": content_type, "text": wire}]}}]
    path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in entries) + trailing)
    return {"session_id": "session", "transcript_path": str(path), "hook_event_name": "Stop"}


def observe(root, payload, agent="owner"):
    evidence.observe(root, agent, payload)


def test_same_native_event_emission_drop_then_accept_through_exact_reader(tmp_path):
    wire, [identity] = emission(tmp_path)
    assert identity["body_sha256"] == hashlib.sha256(BODY.encode()).hexdigest()
    assert BODY in wire and "spec-observation:" in wire
    assert evidence.show(tmp_path, identity) == {"emission": "EMITTED", "arrival": "UNKNOWN", "receivers": []}
    # Emitted-but-dropped has exactly the same generator record and no receiver.
    payload = archive(tmp_path, wire)
    observe(tmp_path, payload)
    result = evidence.show(tmp_path, identity)
    assert result["arrival"] == "HARNESS_OBSERVED"
    assert result["receivers"][0]["turn_id"] == "turn-1"
    assert result["receivers"][0]["record_ordinal"] == 2
    # Public reader takes only an identity, never transcript contents/config.
    command = subprocess.run([sys.executable, "-m", "shantytown.spec_observation", str(tmp_path)],
                             input=json.dumps(identity), capture_output=True, text=True, check=True)
    assert json.loads(command.stdout) == result
    files = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in (tmp_path / "notify/spec-observation").iterdir()}
    observe(tmp_path, payload)
    assert files == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in (tmp_path / "notify/spec-observation").iterdir()}
    assert all(BODY not in data.decode() and wire not in data.decode() for data, _ in files.values())


@pytest.mark.parametrize("change", [
    {"session": "foreign"}, {"turn": None}, {"role": "user"}, {"role": "assistant"},
    {"role": "tool"}, {"kind": "custom_tool_call_output"}, {"kind": "function_call_output"},
    {"content_type": "output_text"}, {"trailing": b'{"partial":'},
])
def test_wrong_or_partial_native_event_never_observed(tmp_path, change):
    wire, [identity] = emission(tmp_path)
    observe(tmp_path, archive(tmp_path, wire, **change))
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"


@pytest.mark.parametrize("key,value", [
    ("agent", "other"), ("harness", "claude"), ("session", "foreign"),
    ("hook_run_id", "hook-2"), ("item", "other-item"), ("generation", 3),
    ("body_sha256", "0" * 64),
])
def test_all_target_identity_fields_must_match(tmp_path, key, value):
    wire, [identity] = emission(tmp_path)
    observe(tmp_path, archive(tmp_path, wire))
    assert evidence.show(tmp_path, identity | {key: value})["arrival"] == "UNKNOWN"


def test_wrong_agent_missing_observer_and_unavailable_source(tmp_path):
    wire, [identity] = emission(tmp_path)
    payload = archive(tmp_path, wire)
    observe(tmp_path, payload, agent="foreign")
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"
    Path(payload["transcript_path"]).unlink()
    with pytest.raises(FileNotFoundError):
        observe(tmp_path, payload)
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"


def test_hook_generation_and_body_are_bound_in_accepted_wire(tmp_path):
    wire, [old] = emission(tmp_path)
    other_wire, [other_hook] = emission(tmp_path, hook_run_id="hook-2")
    assert other_wire != wire
    newer_wire, [newer] = evidence.emitted(tmp_path, "owner", "codex", HOOK,
                                          [{"id": "work-spec", "version": 3}], BODY)
    assert newer_wire != wire
    observe(tmp_path, archive(tmp_path, wire))
    assert evidence.show(tmp_path, old)["arrival"] == "HARNESS_OBSERVED"
    for identity in (other_hook, newer):
        assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"
    # Removing the identity token must not qualify any generation.
    other_root = tmp_path / "other"
    _wire, [target] = emission(other_root)
    observe(other_root, archive(other_root, BODY))
    assert evidence.show(other_root, target)["arrival"] == "UNKNOWN"


def test_new_native_turn_remains_distinct_and_replay_idempotent(tmp_path):
    wire, [identity] = emission(tmp_path)
    payload = archive(tmp_path, wire)
    observe(tmp_path, payload)
    observe(tmp_path, archive(tmp_path, wire, turn="turn-2"))
    assert {r["turn_id"] for r in evidence.show(tmp_path, identity)["receivers"]} == {"turn-1", "turn-2"}


@pytest.mark.parametrize("hook", [{}, HOOK | {"session_id": None}, HOOK | {"hook_run_id": None}])
def test_missing_native_identity_cannot_mint_emission(tmp_path, hook):
    try:
        wire, identities = evidence.emitted(tmp_path, "owner", "codex", hook,
                                            [{"id": "work-spec", "version": 2}], BODY)
    except ValueError:
        pass
    else:
        assert (wire, identities) == (BODY, [])
    assert not (tmp_path / "notify/spec-observation").exists()


def test_original_boundary_dedup_and_ack_semantics_unchanged(tmp_path):
    from datetime import datetime, timezone
    rows = [{"id": "work-spec", "title": "work", "status": "open", "priority": 1,
             "assignee": "owner", "spec_version": 2, "spec_previous_version": 1,
             "spec_changed_at": "2026-10-14T23:00:00Z"}]
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    read = lambda: Answer.complete_read(rows, how="private source fixture")
    first = consume(tmp_path, "owner", read, now=now, observation=("codex", HOOK))
    assert "spec-observation:" in first
    fence = next((tmp_path / "notify").glob("spec-boundary-*.json"))
    before = fence.read_bytes(), fence.stat().st_mtime_ns
    assert consume(tmp_path, "owner", read, now=now, observation=("codex", HOOK)) is None
    assert before == (fence.read_bytes(), fence.stat().st_mtime_ns)
    rows[0].update(spec_version=3, spec_previous_version=2)
    assert "v2 -> v3" in consume(tmp_path, "owner", read, now=now, observation=("codex", HOOK))
    # The injected row reader is the sole tracker surface: no send/ACK API.


def test_unsafe_sources_and_corrupt_evidence_remain_unknown(tmp_path):
    wire, [identity] = emission(tmp_path)
    payload = archive(tmp_path, wire)
    source = Path(payload["transcript_path"])
    linked = tmp_path / "linked.jsonl"
    linked.symlink_to(source)
    with pytest.raises(OSError):
        observe(tmp_path, payload | {"transcript_path": str(linked)})
    fifo = tmp_path / "fifo.jsonl"
    os.mkfifo(fifo)
    with pytest.raises(ValueError):
        observe(tmp_path, payload | {"transcript_path": str(fifo)})
    record = next((tmp_path / "notify/spec-observation").glob("*.json"))
    record.write_text("corrupt")
    assert evidence.show(tmp_path, identity) == {"emission": "UNKNOWN", "arrival": "UNKNOWN"}


@pytest.mark.parametrize("key,value", [
    ("source", "sender-output"), ("turn_id", "foreign-turn"),
    ("record_ordinal", 99), ("record_sha256", "0" * 64),
])
def test_exact_receiver_identity_cannot_borrow_another_event(tmp_path, key, value):
    wire, [identity] = emission(tmp_path)
    observe(tmp_path, archive(tmp_path, wire))
    receiver = evidence.show(tmp_path, identity)["receivers"][0]
    assert evidence.show(tmp_path, identity, receiver=receiver)["arrival"] == "HARNESS_OBSERVED"
    assert evidence.show(tmp_path, identity, receiver=receiver | {key: value})["arrival"] == "UNKNOWN"


def test_symlink_root_cannot_redirect_evidence(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        emission(link)
    assert list(target.iterdir()) == []


def test_oversized_and_malformed_capture_never_observed(tmp_path):
    wire, [identity] = emission(tmp_path)
    payload = archive(tmp_path, wire)
    source = Path(payload["transcript_path"])
    source.write_bytes(source.read_bytes() + b" " * (evidence._CAP + 1))
    with pytest.raises(ValueError):
        observe(tmp_path, payload)
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"
    source.write_bytes(b'[]\n')
    observe(tmp_path, payload)
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"


def test_existing_stats_stop_is_the_observer_boundary(tmp_path, monkeypatch):
    from shantytown import stats
    wire, [identity] = emission(tmp_path)
    payload = archive(tmp_path, wire)
    monkeypatch.setattr(stats, "_agent", lambda: "owner")
    monkeypatch.setattr(stats, "_maybe_export", lambda *args: None)
    # Exercise the actual existing capture entry, while isolating unrelated
    # heartbeat/export/scrub effects from this private receiver fixture.
    from shantytown import owned_work, owned_work_graph
    monkeypatch.setattr(owned_work.OwnedWork, "heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(owned_work_graph, "publish", lambda *a, **k: None)
    monkeypatch.setattr(stats, "_safe_scrub_transcript", lambda *a, **k: None)
    stats.capture(tmp_path, payload)
    assert evidence.show(tmp_path, identity)["arrival"] == "HARNESS_OBSERVED"
    # Missing receiver cannot turn diagnostics into a blocking Stop exception.
    Path(payload["transcript_path"]).unlink()
    stats.capture(tmp_path, payload)


def test_evidence_cap_keeps_existing_receipts_and_does_not_grow(tmp_path, monkeypatch):
    wire, [identity] = emission(tmp_path)
    monkeypatch.setattr(evidence, "_ROWS", 1)
    before = set((tmp_path / "notify/spec-observation").iterdir())
    with pytest.raises(ValueError, match="capped"):
        observe(tmp_path, archive(tmp_path, wire))
    assert before == set((tmp_path / "notify/spec-observation").iterdir())
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"


def test_hook_input_uses_actual_available_payload_without_waiting():
    read, write = os.pipe()
    with os.fdopen(read, "rb") as source:
        try:
            assert evidence.hook_input(source) is None
            os.write(write, json.dumps(HOOK).encode())
            assert evidence.hook_input(source) == HOOK
            os.write(write, b'{"partial":')
            assert evidence.hook_input(source) is None
        finally:
            os.close(write)


def test_receiver_parent_symlink_is_not_followed(tmp_path):
    wire, [identity] = emission(tmp_path)
    payload = archive(tmp_path, wire)
    link = tmp_path / "other-parent"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        observe(tmp_path, payload | {"transcript_path": str(link / "archive.jsonl")})
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"


def test_competing_writer_is_unknown_and_cannot_overwrite_evidence(tmp_path):
    import fcntl
    wire, [identity] = emission(tmp_path)
    directory = evidence._directory(tmp_path)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            observe(tmp_path, archive(tmp_path, wire))
        assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"
    finally:
        os.close(directory)
    assert evidence.show(tmp_path, identity)["arrival"] == "UNKNOWN"
