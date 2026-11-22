"""za4f.2 c5: the ephemeral ledger records harness session id, model and token
usage per job, at report and at forced teardown; unreadable is UNKNOWN, not 0."""
import json
import time

from shantytown import ephemeral as eph, job_usage
from shantytown.stats import _claude_project_dir


def _codex_rollout(state, name, ws, sid="01a2-sess", model="gpt-test", total=150):
    path = state / "shantytown" / "codex" / name / "sessions" / "2026" / "11" / "22" / f"rollout-{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"type": "session_meta", "payload": {"id": sid, "cwd": str(ws)}},
        {"type": "turn_context", "payload": {"model": model, "cwd": str(ws)}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 50,
            "reasoning_output_tokens": 0, "total_tokens": total}}}},
    ]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return path


def test_codex_job_usage_is_read_from_its_own_rollout(tmp_path):
    ws = tmp_path / "ws" / "eph-task-a1b2c3"
    _codex_rollout(tmp_path / "state", "eph-task-a1b2c3", ws)
    _codex_rollout(tmp_path / "state", "eph-task-a1b2c3", tmp_path / "elsewhere", sid="other")
    got = job_usage.collect({"name": "eph-task-a1b2c3", "harness": "codex", "workspace": str(ws)},
                            home=tmp_path / "home", state_base=tmp_path / "state", now=1.0)
    assert got["state"] == "known"
    assert [s["id"] for s in got["sessions"]] == ["01a2-sess"]   # other cwd excluded
    assert got["sessions"][0]["model"] == "gpt-test"
    assert got["totals"]["input_tokens"] == 100 and got["totals"]["cached_input_tokens"] == 40
    assert got["totals"]["output_tokens"] == 50 and got["totals"]["total_tokens"] == 150


def test_claude_job_usage_sums_message_deltas(tmp_path):
    ws = tmp_path / "ws" / "eph-review-a1b2c3"
    d = tmp_path / "home" / ".claude" / "projects" / _claude_project_dir(str(ws))
    d.mkdir(parents=True)
    msg = lambda i, o: {"message": {"model": "claude-test", "usage": {
        "input_tokens": i, "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5,
        "output_tokens": o}}}
    (d / "sess-1.jsonl").write_text(json.dumps(msg(3, 7)) + "\n" + json.dumps(msg(2, 1)) + "\n")
    got = job_usage.collect({"name": "eph-review-a1b2c3", "harness": "claude", "workspace": str(ws)},
                            home=tmp_path / "home", state_base=tmp_path / "state")
    assert got["state"] == "known"
    assert got["sessions"] == [{"id": "sess-1", "model": "claude-test", "usage": got["sessions"][0]["usage"]}]
    t = got["totals"]
    assert (t["input_tokens"], t["cached_input_tokens"], t["cache_write_input_tokens"],
            t["output_tokens"]) == (5, 20, 10, 8)


def test_missing_or_usage_free_transcripts_are_unknown_not_zero(tmp_path):
    rec = {"name": "eph-task-a1b2c3", "harness": "codex", "workspace": str(tmp_path / "ws")}
    got = job_usage.collect(rec, home=tmp_path, state_base=tmp_path / "state")
    assert got["state"] == "unknown" and "totals" not in got
    path = _codex_rollout(tmp_path / "state", rec["name"], tmp_path / "ws")
    path.write_text(path.read_text().splitlines()[0] + "\n")      # meta only, no usage
    got = job_usage.collect(rec, home=tmp_path, state_base=tmp_path / "state")
    assert got["state"] == "unknown" and got["totals"] is None
    assert job_usage.collect(dict(rec, harness="opencode"), home=tmp_path)["state"] == "unknown"


def test_first_result_records_usage_once_and_a_capture_error_never_fails_it(tmp_path, monkeypatch):
    rec = {"name": "eph-task-a1b2c3", "job": "task", "harness": "codex",
           "workspace": str(tmp_path / "ws"), "state": eph.LAUNCHING}
    eph.write(tmp_path, rec)
    calls = []
    monkeypatch.setattr(job_usage, "collect",
                        lambda r, now=None: calls.append(r["name"]) or {"state": "known", "totals": {"total_tokens": 9}})
    eph.record_result(tmp_path, rec["name"], "done", "ok", "report", time.time())
    assert eph.read(tmp_path, rec["name"])["usage"]["totals"]["total_tokens"] == 9
    eph.record_result(tmp_path, rec["name"], "failed", "late", "timeout", time.time())
    assert calls == [rec["name"]]                                  # second ending keeps the first

    other = dict(rec, name="eph-task-d4e5f6")
    eph.write(tmp_path, other)
    def boom(r, now=None):
        raise RuntimeError("disk")
    monkeypatch.setattr(job_usage, "collect", boom)
    out = eph.record_result(tmp_path, other["name"], "failed", "x", "timeout", time.time())
    assert out["result"]["verdict"] == "failed"
    assert eph.read(tmp_path, other["name"])["usage"]["state"] == "unknown"
