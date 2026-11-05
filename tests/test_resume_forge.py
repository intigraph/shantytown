"""Identity-bound terminal facts; failed/truncated reads cannot release work."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from shantytown import deferrals, resume_forge as forge
from shantytown.dispatch import Dispatcher, DeferRefused
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes

SHA = "a" * 40
NOW = datetime(2026, 11, 5, 22, tzinfo=timezone.utc)


def pr(**change):
    return dict(number=7, base={"repo": {"full_name": "owner/repo"}},
                merged=True, merged_at="2026-11-05T21:00:00Z", **change)


@pytest.mark.parametrize("provider", ["github", "forgejo"])
def test_pr_merge_requires_positive_matching_receipt(provider):
    seen = []
    def read(path):
        seen.append(path)
        return pr()
    assert forge.evaluate("pr-merged", f"{provider}/owner/repo#7", read=read)[0] is True
    assert seen == ["/pulls/7"]
    data = pr()
    data.update(merged=False, state="closed")
    assert forge.evaluate("pr-merged", f"{provider}/owner/repo#7", read=lambda _: data)[0] is False
    for patch in ({"merged": "true"}, {"number": 8}, {"merged_at": None},
                  {"base": {"repo": {"full_name": "other/repo"}}}):
        data = pr(); data.update(patch)
        assert forge.evaluate("pr-merged", f"{provider}/owner/repo#7", read=lambda _: data)[0] is None


def inventory(*, check="completed", conclusion="success", run="completed", status="success"):
    def read(path):
        if "/check-runs?" in path:
            return {"total_count": 1, "check_runs": [dict(id=1, head_sha=SHA, status=check,
                                                         conclusion=conclusion)]}
        if path.startswith("/actions/runs?"):
            return {"total_count": 1, "workflow_runs": [dict(id=2, head_sha=SHA, status=run,
                                                            conclusion=conclusion)]}
        return {"sha": SHA, "total_count": 1, "statuses": [dict(id=3, state=status)]}
    return read


@pytest.mark.parametrize("provider", ["github", "forgejo"])
def test_ci_terminal_failure_is_completion_not_a_green_verdict(provider):
    marker = f"{provider}/owner/repo@{SHA}"
    assert forge.evaluate("ci-complete", marker, read=inventory())[0] is True
    result = forge.evaluate("ci-complete", marker,
                           read=inventory(conclusion="failure", status="failure", run="failure"))
    assert result[0] is True and "inspect" in result[1]
    assert forge.evaluate("ci-complete", marker, read=inventory(run="queued"))[0] is False
    assert forge.evaluate("ci-complete", marker, read=inventory(status="pending"))[0] is False


def test_early_green_does_not_hide_queued_parent_or_missing_conclusion():
    marker = f"github/owner/repo@{SHA}"
    assert forge.evaluate("ci-complete", marker, read=inventory(run="in_progress"))[0] is False
    assert forge.evaluate("ci-complete", marker, read=inventory(check="queued"))[0] is False
    assert forge.evaluate("ci-complete", marker, read=inventory(conclusion=None))[0] is None


@pytest.mark.parametrize("problem", ["empty", "wrong-head", "wrong-status-sha", "count", "duplicate", "malformed"])
def test_incomplete_ci_evidence_is_unknown(problem):
    base = inventory()
    def read(path):
        data = base(path)
        if problem == "empty":
            field = next(key for key in ("statuses", "workflow_runs", "check_runs") if key in data)
            data.update(total_count=0, **{field: []})
        elif problem == "wrong-head" and "workflow_runs" in data:
            data["workflow_runs"][0]["head_sha"] = "b" * 40
        elif problem == "wrong-status-sha" and "statuses" in data:
            data["sha"] = "b" * 40
        elif problem == "count":
            data["total_count"] = 2000
        elif problem == "duplicate":
            field = next(key for key in ("statuses", "workflow_runs", "check_runs") if key in data)
            data[field] *= 2; data["total_count"] = 2
        elif problem == "malformed":
            return []
        return data
    assert forge.evaluate("ci-complete", f"github/owner/repo@{SHA}", read=read)[0] is None


def test_pagination_requires_complete_stable_inventory():
    calls = []
    def read(path):
        calls.append(path)
        first = parse_qs(urlsplit(path).query)["page"] == ["1"]
        return {"total_count": 101, "rows": [dict(id=i) for i in (range(100) if first else [100])]}
    assert len(forge._pages(read, "/path", "rows", "github")) == 101
    assert len(calls) == 2
    with pytest.raises(ValueError):
        forge._pages(lambda _: {"total_count": 1, "rows": []}, "/path", "rows", "github")


@pytest.mark.parametrize("kind,arg", [
    ("pr-merged", "https://evil.test/owner/repo#1"),
    ("pr-merged", "github/../../repo#1"),
    ("pr-merged", "github/owner/repo#0"),
    ("ci-complete", "github/owner/repo@main"),
    ("ci-complete", "github/owner/repo@$(id)"),
])
def test_markers_cannot_select_commands_urls_paths_or_moving_heads(kind, arg):
    with pytest.raises(ValueError):
        forge.validate(kind, arg)
    assert forge.evaluate(kind, arg, read=lambda _: pytest.fail("read on invalid input"))[0] is None


def test_transport_failure_stays_unknown_and_redacts_exception_body():
    def fail(_):
        raise OSError("credential-not-for-output")
    answer, reason = forge.evaluate("pr-merged", "github/owner/repo#7", read=fail)
    assert answer is None and "credential-not-for-output" not in reason


@pytest.mark.parametrize("marker", ["pr-merged:github/owner/repo#7",
                                  "ci-complete:forgejo/owner/repo@" + SHA])
def test_real_defer_writer_accepts_fixed_event_and_rejects_bad_identity(tmp_path, marker):
    tracker = FilesTracker(tmp_path / "items")
    tracker.update("item-1", title="event wait", status="open", assignee="owner", priority=1)
    dispatcher = Dispatcher(FilesRegistry(tmp_path / "crew"), tracker, NullPanes())
    dispatcher.defer("item-1", "external", "resume_when: " + marker,
                     until="2099-11-07T22:00:00Z")
    item = tracker.get("item-1")
    assert item.status == "deferred" and marker in item.notes
    before = tracker._path("item-1").read_bytes()
    with pytest.raises(DeferRefused):
        dispatcher.defer("item-1", "external", "resume_when: ci-complete:github/owner/repo@main",
                         until="2099-11-07T22:00:00Z")
    assert tracker._path("item-1").read_bytes() == before


def test_scheduled_sweeper_rechecks_event_before_release_and_preserves_holds(tmp_path, monkeypatch):
    from shantytown import notify
    row = dict(id="item-1", title="wait", status="deferred", assignee="owner",
               notes=f"resume_when: ci-complete:github/owner/repo@{SHA}",
               labels=["blocked:external"], defer_until=(NOW + timedelta(days=1)).isoformat())
    calls, answers = [], iter([(True, "terminal"), (False, "queued again")])
    monkeypatch.setattr(forge, "evaluate", lambda *a: next(answers))
    def release(identifier):
        calls.append(identifier)
        row.update(status="open", defer_until=None)
    alerter = notify.DeferralAlerter(tmp_path, None, None, read=lambda: [dict(row)],
        show=lambda _: dict(row), release=release, now=lambda: NOW, push=lambda *a: None)
    alerter.sweep()
    assert not calls and row["status"] == "deferred"
    monkeypatch.setattr(forge, "evaluate", lambda *a: (True, "terminal"))
    alerter.sweep()
    assert calls == ["item-1"] and row["status"] == "open"


@pytest.mark.parametrize("change", [
    {"labels": ["blocked:human"]}, {"labels": ["blocked:access"]},
    {"notes": "resume_when: pr-merged:github/owner/repo#7\nWait for owner GO too"},
    {"dependencies": [{"dependency_type": "blocks", "status": "open"}]},
])
def test_met_event_cannot_override_other_gates(monkeypatch, change):
    monkeypatch.setattr(forge, "evaluate", lambda *a: (True, "merged"))
    row = dict(id="item-1", status="deferred", labels=["blocked:external"],
               notes="resume_when: pr-merged:github/owner/repo#7",
               defer_until=(NOW + timedelta(days=1)).isoformat())
    row.update(change)
    finding = deferrals.evaluate([row], NOW)[0]
    assert finding.met and not deferrals.can_release(row, finding, NOW)
