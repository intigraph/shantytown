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
