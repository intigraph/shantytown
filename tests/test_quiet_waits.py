from types import SimpleNamespace

import pytest

from shantytown import quiet_waits

TARGET = "github/example/project@" + "a" * 40


def row(**kw):
    return dict(id="work", status="in_progress", priority=0,
                notes="resume_when: ci-terminal:" + TARGET, **kw)


@pytest.mark.parametrize("answer", [False, None, True])
def test_pending_unknown_and_terminal_keep_original_status(monkeypatch, answer):
    original = row()
    def evaluate(rows, now, root):
        assert rows[0]["status"] == "deferred"
        assert rows[0]["defer_until"] is None
        return [SimpleNamespace(bead="work", met=answer is True,
                                read_error=answer is None, untestable="")]
    monkeypatch.setattr(quiet_waits, "evaluate", evaluate)
    assert quiet_waits.ready([original]) == ([original] if answer is True else [])
    assert original["status"] == "in_progress" and "defer_until" not in original


def test_unrecorded_and_malformed_waits_stay_visible(monkeypatch):
    monkeypatch.setattr(quiet_waits, "evaluate", lambda *a, **kw: pytest.fail("unexpected read"))
    for notes in ["CI pending", "resume_when: ci-terminal:short", "",
                  "resume_when: ci-terminal:" + TARGET + "\nresume_when: closed:other"]:
        item = row()
        item["notes"] = notes
        assert quiet_waits.ready([item]) == [item]


def test_reader_failure_retains_wait_and_reports_unknown(monkeypatch):
    def failed(*a, **kw):
        raise OSError("fixture unavailable")
    monkeypatch.setattr(quiet_waits, "evaluate", failed)
    messages = []
    assert quiet_waits.ready([row()], log=messages.append) == []
    assert any("UNKNOWN" in message for message in messages)


def test_installed_wait_and_explicit_lead_clearing_marker(monkeypatch):
    item = row()
    item["notes"] = "resume_when: installed:bobbin>=0.1.0"
    monkeypatch.setattr(quiet_waits, "evaluate", lambda *a, **kw: [])
    assert quiet_waits.ready([item]) == []
    item["notes"] = "Lead resumed source work; prior event retained in history"
    assert quiet_waits.ready([item]) == [item]


@pytest.mark.parametrize("status,conclusion,wakes", [("queued", None, False),
    ("in_progress", None, False), ("completed", "success", True),
    ("completed", "failure", True), ("completed", "cancelled", True)])
def test_actual_event_reader_to_quiet_wait_boundary(monkeypatch, status, conclusion, wakes):
    from shantytown import deferrals
    from test_resume_forge_events import fake_ci
    reader = fake_ci(run_status=status, conclusion=conclusion)
    monkeypatch.setattr(quiet_waits, "evaluate", lambda rows, now, root:
        deferrals.evaluate(rows, now, root=root, forge_reader=reader))
    item = row()
    assert quiet_waits.ready([item]) == ([item] if wakes else [])


def test_idle_sweep_rearms_after_pending_event_becomes_terminal(tmp_path, monkeypatch):
    from shantytown import feed_check, deferrals
    from test_lead_haul_feed_by_tend import _lead_hauling_world
    from test_resume_forge_events import fake_ci
    alerter, panes = _lead_hauling_world(tmp_path, monkeypatch, [])
    item = row(assignee="dearing", title="CI wait")
    alerter._bd_ready = lambda: []
    alerter._bd_in_progress = lambda cwd: [item]
    monkeypatch.setattr(feed_check, "idle_resumable_codex", lambda *a, **kw: ["dearing"])
    state = {"terminal": False}
    def evaluate(rows, now, root):
        terminal = state["terminal"]
        return deferrals.evaluate(rows, now, root=root, forge_reader=fake_ci(
            run_status="completed" if terminal else "queued",
            conclusion="failure" if terminal else None))
    monkeypatch.setattr(quiet_waits, "evaluate", evaluate)
    assert alerter.sweep([]) == []
    assert not panes.sent
    state["terminal"] = True
    assert alerter.sweep([]) == ["dearing"]
    assert len(panes.sent) == 1 and "HAUL RESUME" in panes.sent[0][1]
    assert alerter.sweep([]) == []
    assert len(panes.sent) == 1
