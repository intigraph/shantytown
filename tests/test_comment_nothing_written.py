"""A comment write sd refused with "nothing was written" must say so (aegis-epi).

sd exits 4 when its compare-and-set guard did not match: the server committed
nothing. st used to print only "work item operation unproven: RuntimeError",
which reads like a write that may have landed, and a flip watch took it as a
rollback trigger. These pin the definite outcome and the printed cause.
"""
from __future__ import annotations

import subprocess
from argparse import Namespace

import pytest

from shantytown import br as br_mod
from shantytown import cli

LOST = ("sd: another writer changed it first for comment 180 on aegis-g51c; "
        "nothing was written. Re-read before retrying.\n")


class _Stub(br_mod.BrTracker):
    def __init__(self, tool: str, rc: int, stderr: str):
        self._tool = tool
        self._rc = rc
        self._stderr = stderr
        self.repo = None

    def _bd_for(self, item_id, *args):
        return subprocess.CompletedProcess(args, self._rc, stdout="", stderr=self._stderr)


def test_sd_conflict_on_a_comment_is_nothing_written_with_its_cause():
    with pytest.raises(br_mod.NothingWritten) as caught:
        br_mod.append_comment(_Stub("sd", 4, LOST), "aegis-g51c", "body")
    assert "comment 180 on aegis-g51c" in str(caught.value)
    assert "nothing was written" in str(caught.value)


def test_other_failures_stay_unproven():
    # br's exit codes are not sd's, and a non-conflict sd failure may have landed.
    for tool, rc in (("br", 4), ("sd", 1)):
        with pytest.raises(RuntimeError) as caught:
            br_mod.append_comment(_Stub(tool, rc, "boom\n"), "aegis-x", "body")
        assert not isinstance(caught.value, br_mod.NothingWritten)


def _run_item(monkeypatch, exc):
    import shantytown.work_item as work_item

    def boom(args, tracker):
        raise exc
    monkeypatch.setattr(work_item, "command", boom)
    monkeypatch.setattr(cli, "_tracker", lambda a: None)
    return cli._run_command(Namespace(cmd="item"))


def test_cli_names_a_write_that_landed_nothing(monkeypatch, capsys):
    rc = _run_item(monkeypatch, br_mod.NothingWritten(f"sd comments add aegis-g51c wrote nothing: {LOST}"))
    err = capsys.readouterr().err
    assert rc == 2
    assert err.startswith("work item not written: ")
    assert "comment 180 on aegis-g51c" in err
    assert "unproven" not in err


def test_cli_unproven_now_carries_its_cause(monkeypatch, capsys):
    rc = _run_item(monkeypatch, RuntimeError("comment readback unproven; write may have landed"))
    err = capsys.readouterr().err
    assert rc == 2
    assert "work item operation unproven: RuntimeError: comment readback unproven" in err


def test_cli_cause_is_bounded_and_bearer_redacted(monkeypatch, capsys):
    secret = "Authorization: Bearer " + "q" * 40
    _run_item(monkeypatch, RuntimeError(f"401 from server with {secret} " + "x" * 2000))
    err = capsys.readouterr().err
    assert "q" * 40 not in err
    assert len(err) < 700


TOKEN = "Z" * 40


def _at_cut(cut: int, keep: int = 10, lead: str = "") -> str:
    """A message whose bearer token straddles a `cut`-char bound by `keep` chars."""
    header = "Authorization: Bearer "
    return lead + "x" * (cut - len(lead) - len(header) - keep) + header + TOKEN


@pytest.mark.parametrize("keep", [1, 10, 23, 24, 40])
def test_cli_bound_never_keeps_a_token_fragment(monkeypatch, capsys, keep):
    # grant's boundary control: truncating BEFORE redaction kept 10 token chars.
    _run_item(monkeypatch, RuntimeError(_at_cut(400, keep)))
    err = capsys.readouterr().err
    assert "Z" not in err
    if keep >= len("[REDACTED]"):
        assert "[REDACTED]" in err  # the mask survives the bound, not just its prefix


@pytest.mark.parametrize("rc,tool,cut", [(4, "sd", 200), (1, "br", 160)])
def test_lower_level_cuts_redact_first(rc, tool, cut):
    # _failure_reason's 200 cut (sd exit 4) and append_comment's 160 cut (br).
    with pytest.raises(RuntimeError) as caught:
        br_mod.append_comment(_Stub(tool, rc, _at_cut(cut)), "aegis-x", "body")
    assert "Z" not in str(caught.value)


def test_a_short_value_after_bearer_is_masked():
    assert "abc" not in br_mod.redact_cause("401: bearer abc refused")
    assert br_mod.redact_cause("nothing was written") == "nothing was written"


KNOWN = "K" * 32


def _known(monkeypatch):
    import shantytown.stats as stats
    monkeypatch.setattr(stats, "_known_quipu_bearers", lambda: (KNOWN.encode(),))


def _bare_at_cut(cut: int, keep: int = 10) -> str:
    """A known token with NO bearer prefix, straddling a `cut`-char bound."""
    return "x" * (cut - keep) + KNOWN


@pytest.mark.parametrize("keep", [1, 10, 31])
def test_a_known_token_is_redacted_before_the_cli_bound(monkeypatch, capsys, keep):
    # Only the exact-token match can see a bare token, and only while it is whole.
    _known(monkeypatch)
    _run_item(monkeypatch, RuntimeError(_bare_at_cut(400, keep)))
    assert "K" not in capsys.readouterr().err


@pytest.mark.parametrize("rc,tool,cut", [(4, "sd", 200), (1, "br", 160)])
def test_a_known_token_is_redacted_before_lower_level_cuts(monkeypatch, rc, tool, cut):
    _known(monkeypatch)
    with pytest.raises(RuntimeError) as caught:
        br_mod.append_comment(_Stub(tool, rc, _bare_at_cut(cut)), "aegis-x", "body")
    assert "K" not in str(caught.value)


# A contended comment can commit after st's subprocess limit kills sd. st then
# printed "unproven: TimeoutExpired" for a comment that had landed (aegis-epi,
# reproduced with four concurrent `st work item comment` on one item).

@pytest.fixture(autouse=True)
def _writer_is_hammond(monkeypatch):
    # The read-back matches the author st writes as; pin it so no test asks
    # this host's real identity service.
    import shantytown.actor_identity as actor_identity
    monkeypatch.setattr(actor_identity, "authenticated_actor", lambda **_: None)
    monkeypatch.setenv("SHANTY_AGENT", "hammond")


def _timing_out_tracker(rows_after):
    import json
    from shantytown.protocols import WorkItem
    from shantytown.sd import SdTracker

    class TimesOut(SdTracker):
        def __init__(self):
            self.writes = 0

        def get(self, item_id):
            return WorkItem(item_id)

        def _bd_for(self, item_id, *command):
            if command[:2] == ("comments", "add"):
                self.writes += 1
                raise subprocess.TimeoutExpired(["sd", *command], 30)
            assert command == ("comments", item_id, "--json")
            if callable(rows_after):
                return rows_after(command)
            return subprocess.CompletedProcess(command, 0, json.dumps(rows_after), "")

    return TimesOut()


def _comment(tmp_path, tracker, text="the body"):
    from shantytown import work_item
    body = tmp_path / "comment.txt"
    body.write_text(text)
    operation = Namespace(item="aegis-x", item_action="comment", dry_run=False, file=body)
    return work_item.command(operation, tracker)


def _now(offset=0):
    from datetime import datetime, timedelta, timezone
    at = datetime.now(timezone.utc) + timedelta(seconds=offset)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_timed_out_comment_that_landed_is_verified_without_a_resend(tmp_path):
    tracker = _timing_out_tracker([{"text": "the body", "created_at": _now()}])
    assert _comment(tmp_path, tracker) == {"id": "aegis-x", "comment": "verified"}
    assert tracker.writes == 1


def test_timed_out_comment_absent_from_readback_stays_unproven(tmp_path):
    tracker = _timing_out_tracker([{"text": "other", "created_at": _now()}])
    with pytest.raises(RuntimeError, match="timed out after 30s.*may still land") as caught:
        _comment(tmp_path, tracker)
    assert not isinstance(caught.value, br_mod.NothingWritten)
    assert tracker.writes == 1


def test_timed_out_comment_ignores_an_identical_older_comment(tmp_path):
    # The same text posted an hour ago is not proof this attempt landed.
    tracker = _timing_out_tracker([{"text": "the body", "created_at": _now(-3600)}])
    with pytest.raises(RuntimeError, match="timed out"):
        _comment(tmp_path, tracker)


@pytest.mark.parametrize("created_at", [None, "", "not-a-time", "2026-10-27T15:36:26"])
def test_timed_out_comment_needs_a_readable_zoned_time(tmp_path, created_at):
    row = {"text": "the body"}
    if created_at is not None:
        row["created_at"] = created_at
    with pytest.raises(RuntimeError, match="timed out"):
        _comment(tmp_path, _timing_out_tracker([row]))


def _read_times_out(command):
    raise subprocess.TimeoutExpired(["sd", *command], 30)


def _read_fails(command):
    return subprocess.CompletedProcess(command, 1, "", "sd: quipu 503\n")


def _read_garbled(command):
    return subprocess.CompletedProcess(command, 0, "{not json", "")


@pytest.mark.parametrize("read", [_read_times_out, _read_fails, _read_garbled],
                         ids=["timeout", "sd-error", "bad-json"])
def test_failed_readback_keeps_the_may_still_land_wording(tmp_path, read):
    # A read-back that cannot answer says nothing about the write; a bare
    # "comments failed" would invite a blind retry and a duplicate comment.
    tracker = _timing_out_tracker(read)
    with pytest.raises(RuntimeError,
                       match="timed out after 30s.*readback failed.*may still land; "
                             "verify exact readback before retrying") as caught:
        _comment(tmp_path, tracker)
    assert not isinstance(caught.value, br_mod.NothingWritten)
    assert tracker.writes == 1


def test_same_text_by_another_author_is_not_verified(tmp_path):
    tracker = _timing_out_tracker(
        [{"text": "the body", "author": "sattler", "created_at": _now()}])
    with pytest.raises(RuntimeError, match="timed out.*may still land"):
        _comment(tmp_path, tracker)


def test_same_text_by_the_writer_is_verified(tmp_path):
    tracker = _timing_out_tracker(
        [{"text": "the body", "author": "hammond", "created_at": _now()}])
    assert _comment(tmp_path, tracker) == {"id": "aegis-x", "comment": "verified"}


def test_skew_allowance_counts_a_comment_stamped_20s_early(tmp_path):
    # The tracker's clock may run behind st's; 30s back still counts.
    tracker = _timing_out_tracker(
        [{"text": "the body", "author": "hammond", "created_at": _now(-20)}])
    assert _comment(tmp_path, tracker) == {"id": "aegis-x", "comment": "verified"}


def test_skew_allowance_stops_at_30s(tmp_path):
    tracker = _timing_out_tracker(
        [{"text": "the body", "author": "hammond", "created_at": _now(-40)}])
    with pytest.raises(RuntimeError, match="timed out.*may still land"):
        _comment(tmp_path, tracker)
