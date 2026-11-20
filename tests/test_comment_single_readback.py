"""An st comment never re-reads the item's whole comment family (aegis-n0wc).

On sd every `comments` list read is the item's whole comment family: on a
long-running item that is 3-4 s of quipu store time per read. st used to read
the list right after `comments add`, throw it away, then read it again to
verify. Now sd's receipt names the new comment's position and st reads exactly
that comment (Sattler B2 ruling: the receipt says what to read, it does not
verify by itself). Without a receipt, one list readback, as before.
"""
from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from types import SimpleNamespace

import pytest

from shantytown import br as br_mod
from shantytown import work_item
from shantytown.answer import Answer


class _Recorder(br_mod.BrTracker):
    """An sd tracker; receipt=True makes `comments add --json` answer like sd."""

    def __init__(self, receipt=False, landed=None):
        self._tool = "sd"
        self.repo = None
        self.calls: list[tuple[str, ...]] = []
        self.rows: list[dict] = []
        self.receipt = receipt
        self.exact_reads: list[tuple] = []
        self.landed = landed

    def get(self, item_id):
        return SimpleNamespace(id=item_id)

    def _bd_for(self, item_id, *args):
        self.calls.append(args)
        if args[:2] == ("comments", "add"):
            path = args[args.index("--file") + 1]
            with open(path, encoding="utf-8") as handle:
                self.rows.append({"text": handle.read()})
            out = ""
            if self.receipt and "--json" in args:
                out = json.dumps({"id": len(self.rows), "issue_id": item_id,
                                  "author": "ian", "text": self.rows[-1]["text"],
                                  "created_at": "t", "tx": 1355600})
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(self.rows), stderr="")

    def comment_landed(self, item_id, index, body):
        self.exact_reads.append((item_id, index, body))
        if self.landed is not None:
            return self.landed
        row = self.rows[index - 1] if 0 < index <= len(self.rows) else None
        return Answer.complete_read(bool(row and row["text"] == body), how="test")


def _reads(calls):
    return [c for c in calls if c[:1] == ("comments",) and c[1:2] != ("add",)]


def _command(tmp_path, trk):
    body = tmp_path / "body.md"
    body.write_text("finding\n")
    args = Namespace(item="aegis-x", item_action="comment", file=str(body), dry_run=False)
    return work_item.command(args, trk)


def test_submit_does_not_read_the_comment_list():
    trk = _Recorder()
    assert work_item._comments(trk, "aegis-x", "body") is None
    assert [c[:2] for c in trk.calls] == [("comments", "add")]


def test_receipt_verifies_by_one_exact_read_and_no_list_read(tmp_path):
    trk = _Recorder(receipt=True)
    assert _command(tmp_path, trk) == {"id": "aegis-x", "comment": "verified"}
    assert _reads(trk.calls) == []
    assert trk.exact_reads == [("aegis-x", 1, "finding\n")]


def test_receipt_whose_comment_is_not_there_is_unproven_without_listing(tmp_path):
    trk = _Recorder(receipt=True, landed=Answer.complete_read(False, how="test"))
    with pytest.raises(RuntimeError, match="readback unproven"):
        _command(tmp_path, trk)
    assert _reads(trk.calls) == []


def test_unreadable_exact_read_is_unproven_without_listing(tmp_path):
    trk = _Recorder(receipt=True, landed=Answer.capped(False, how="test", caveat="408"))
    with pytest.raises(RuntimeError, match="readback unreadable"):
        _command(tmp_path, trk)
    assert _reads(trk.calls) == []


def test_without_a_receipt_one_list_read_verifies(tmp_path):
    trk = _Recorder(receipt=False)
    assert _command(tmp_path, trk) == {"id": "aegis-x", "comment": "verified"}
    assert len(_reads(trk.calls)) == 1
    assert trk.exact_reads == []


def test_without_a_receipt_a_missing_comment_is_still_unproven(tmp_path):
    trk = _Recorder(receipt=False)
    real = trk._bd_for

    def lost(item_id, *args):
        result = real(item_id, *args)
        if args[:2] == ("comments", "add"):
            trk.rows.clear()
        return result
    trk._bd_for = lost
    with pytest.raises(RuntimeError, match="readback unproven"):
        _command(tmp_path, trk)


@pytest.mark.parametrize("stdout", [
    "",
    "not json",
    json.dumps({"id": 3, "issue_id": "aegis-other", "tx": 9}),
    json.dumps({"id": 3, "issue_id": "aegis-x", "tx": 0}),
    json.dumps({"id": 3, "issue_id": "aegis-x", "tx": None}),
    json.dumps({"id": 0, "issue_id": "aegis-x", "tx": 9}),
    json.dumps({"id": "3", "issue_id": "aegis-x", "tx": 9}),
    json.dumps({"id": True, "issue_id": "aegis-x", "tx": 9}),
])
def test_only_an_exact_committed_receipt_names_a_position(stdout):
    assert br_mod.comment_receipt(stdout, "aegis-x") is None


def test_exact_committed_receipt_names_its_position():
    out = json.dumps({"id": 7, "issue_id": "aegis-x", "tx": 1355600})
    assert br_mod.comment_receipt(out, "aegis-x") == 7
    envelope = json.dumps({"result": {"id": 7, "issue_id": "aegis-x", "tx": 1355600}})
    assert br_mod.comment_receipt(envelope, "aegis-x") == 7


def test_br_never_asks_for_a_receipt():
    trk = _Recorder(receipt=True)
    trk._tool = "br"
    assert br_mod.append_comment(trk, "aegis-x", "body") is None
    assert "--json" not in trk.calls[0]


def _plate(monkeypatch, rows):
    from shantytown import seeds_plate
    seen = []

    def query(proof, text, timeout):
        seen.append(text)
        return {"rows": rows}
    monkeypatch.setattr(seeds_plate, "_query", query)
    proof = SimpleNamespace(graph="https://seeds.local/project/aegis")
    return seeds_plate, proof, seen


ITEM = "https://seeds.local/item/aegis-x"
G = "https://seeds.local/project/aegis"


def test_exact_read_names_one_subject_never_the_family(monkeypatch):
    plate, proof, seen = _plate(monkeypatch, [
        {"graph": G, "parent": ITEM, "position": 4, "text": "b"}])
    answer = plate.comment_landed(proof, "aegis-x", 4, "b")
    assert answer.complete and answer.exact() is True
    assert "<https://seeds.local/item/aegis-x/comment/4>" in seen[0]
    assert "?s <https://schema.org/parentItem>" not in seen[0]


@pytest.mark.parametrize("row", [
    {"graph": G, "parent": ITEM + "y", "position": 4, "text": "b"},
    {"graph": G, "parent": ITEM, "position": 5, "text": "b"},
    {"graph": G, "parent": ITEM, "position": 4, "text": "b\n"},
    {"graph": "https://other/graph", "parent": ITEM, "position": 4, "text": "b"},
])
def test_exact_read_mismatch_is_a_complete_no(monkeypatch, row):
    plate, proof, _ = _plate(monkeypatch, [row])
    answer = plate.comment_landed(proof, "aegis-x", 4, "b")
    assert answer.complete and answer.exact() is False


def test_exact_read_absent_is_complete_no_and_ambiguous_is_capped(monkeypatch):
    plate, proof, _ = _plate(monkeypatch, [])
    assert plate.comment_landed(proof, "aegis-x", 4, "b").exact() is False
    row = {"graph": G, "parent": ITEM, "position": 4, "text": "b"}
    plate, proof, _ = _plate(monkeypatch, [row, dict(row, graph=G + "#seeds-ephemeral")])
    assert not plate.comment_landed(proof, "aegis-x", 4, "b").complete
