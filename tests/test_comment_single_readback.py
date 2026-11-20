"""One st comment reads the comment family once, for its readback (aegis-n0wc).

On sd every `comments` read is the item's whole comment family: on a
long-running item that is 3-4 s of quipu store time per read. The submit
helper used to read the list right after `comments add` and throw it away,
then the caller read it again to verify, so every comment paid two family
reads after the write. These pin one.
"""
from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from types import SimpleNamespace

from shantytown import br as br_mod
from shantytown import work_item


class _Recorder(br_mod.BrTracker):
    def __init__(self):
        self._tool = "sd"
        self.repo = None
        self.calls: list[tuple[str, ...]] = []
        self.rows: list[dict] = []

    def get(self, item_id):
        return SimpleNamespace(id=item_id)

    def _bd_for(self, item_id, *args):
        self.calls.append(args)
        if args[:2] == ("comments", "add"):
            path = args[args.index("--file") + 1]
            with open(path, encoding="utf-8") as handle:
                self.rows.append({"text": handle.read()})
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(self.rows), stderr="")


def _reads(calls):
    return [c for c in calls if c[:1] == ("comments",) and c[1:2] != ("add",)]


def test_submit_does_not_read_the_comment_list():
    trk = _Recorder()
    assert work_item._comments(trk, "aegis-x", "body") == []
    assert [c[:2] for c in trk.calls] == [("comments", "add")]


def test_readback_alone_still_reads_the_list():
    trk = _Recorder()
    trk.rows.append({"text": "earlier"})
    assert work_item._comments(trk, "aegis-x") == [{"text": "earlier"}]
    assert len(_reads(trk.calls)) == 1


def test_one_comment_command_reads_the_family_once_and_verifies(tmp_path):
    body = tmp_path / "body.md"
    body.write_text("finding\n")
    trk = _Recorder()
    args = Namespace(item="aegis-x", item_action="comment", file=str(body), dry_run=False)
    assert work_item.command(args, trk) == {"id": "aegis-x", "comment": "verified"}
    assert len(_reads(trk.calls)) == 1


def test_a_comment_the_readback_does_not_show_is_still_unproven(tmp_path):
    body = tmp_path / "body.md"
    body.write_text("finding\n")
    trk = _Recorder()
    real = trk._bd_for

    def lost(item_id, *args):
        result = real(item_id, *args)
        if args[:2] == ("comments", "add"):
            trk.rows.clear()  # accepted, but the readback does not show it
        return result
    trk._bd_for = lost
    args = Namespace(item="aegis-x", item_action="comment", file=str(body), dry_run=False)
    try:
        work_item.command(args, trk)
    except RuntimeError as unproven:
        assert "readback unproven" in str(unproven)
    else:
        raise AssertionError("a comment missing from the readback was reported verified")
