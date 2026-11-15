from argparse import Namespace
from copy import deepcopy

import pytest

from shantytown.sd import SdTracker
from shantytown.review_reservation import command, reviewer


class Seeds(SdTracker):
    def __init__(self):
        self.rows = {"st-1": dict(id="st-1", revision=3, labels=["P0", "blocked:external"],
                                 assignee="author", status="in_progress", comments=[]),
                     "st-old": dict(id="st-old", revision=7, labels=["reviewer:peer"],
                                   assignee="previous-author", status="closed", comments=[])}
        self.writes = []
        self.fault = None

    def stranded_read(self, item):
        return deepcopy(self.rows[item])

    def update(self, item, **fields):
        self.writes.append(fields)
        if self.fault:
            raise self.fault
        row = self.rows[item]
        assert fields["if_revision"] == row["revision"]
        row["labels"] = fields["set_labels"].split(",")
        row["revision"] += 1
        row["comments"].append({"text": fields["transition_comment"]})


def args(**kw):
    return Namespace(**(dict(item="st-1", reviewer=None, inherit_from=None,
                            replace_reviewer=None, contributor=[], dry_run=False) | kw))


def test_reservation_survives_new_pr_and_preserves_gate_and_owner():
    seeds = Seeds()
    assert command(args(reviewer="peer"), seeds)["result"] == "verified"
    assert seeds.rows["st-1"]["labels"] == ["P0", "blocked:external", "reviewer:peer"]
    assert seeds.rows["st-1"]["assignee"] == "author"
    assert command(args(reviewer="peer"), seeds)["result"] == "unchanged"
    assert command(args(), seeds)["reviewer"] == "peer"
    assert len(seeds.writes) == 1


def test_successor_inherits_same_peer_and_cannot_silently_book_another():
    seeds = Seeds()
    command(args(inherit_from="st-old"), seeds)
    with pytest.raises(ValueError, match="already reserves peer"):
        command(args(reviewer="other"), seeds)
    assert len(seeds.writes) == 1
    command(args(reviewer="other", replace_reviewer="peer"), seeds)
    assert reviewer(seeds.rows["st-1"]) == "other"
    assert seeds.rows["st-old"]["revision"] == 7


@pytest.mark.parametrize("who,contributors", [("author", []), ("peer", ["peer"])])
def test_author_or_folded_contributor_cannot_be_reserved(who, contributors):
    seeds = Seeds()
    with pytest.raises(ValueError, match="author/contributor"):
        command(args(reviewer=who, contributor=contributors), seeds)
    assert not seeds.writes


@pytest.mark.parametrize("labels", [None, ["reviewer:a", "reviewer:b"], ["reviewer:"], [{}]])
def test_malformed_or_ambiguous_reservations_are_unknown(labels):
    seeds = Seeds()
    seeds.rows["st-1"]["labels"] = labels
    with pytest.raises(ValueError):
        command(args(reviewer="peer"), seeds)
    assert not seeds.writes


def test_conflict_or_indeterminate_write_never_retries():
    seeds = Seeds()
    seeds.fault = TimeoutError("may have committed")
    with pytest.raises(TimeoutError):
        command(args(reviewer="peer"), seeds)
    assert len(seeds.writes) == 1


def test_preview_does_not_reserve():
    seeds = Seeds()
    assert command(args(reviewer="peer", dry_run=True), seeds)["result"] == "planned"
    assert not seeds.writes


def test_concurrent_reassignment_is_not_overwritten():
    seeds = Seeds()
    command(args(reviewer="peer"), seeds)
    with pytest.raises(ValueError, match="expected reviewer changed"):
        command(args(reviewer="other", replace_reviewer="outdated"), seeds)
    assert len(seeds.writes) == 1


def test_write_that_does_not_read_back_is_unknown_not_verified():
    seeds = Seeds()
    seeds.update = lambda *a, **kw: None
    with pytest.raises(RuntimeError, match="outcome UNKNOWN"):
        command(args(reviewer="peer"), seeds)


def test_real_parser_exposes_inheritance_and_contributor_recusal():
    from shantytown.cli import build_parser
    parsed = build_parser().parse_args([
        "work", "item", "review-reservation", "st-1", "--inherit-from", "st-old",
        "--contributor", "peer", "--dry-run"])
    seeds = Seeds()
    with pytest.raises(ValueError, match="author/contributor"):
        command(parsed, seeds)
    assert not seeds.writes


def test_explicit_revision_fence_and_unrelated_action_flags_are_not_ignored():
    from shantytown import work_item
    seeds = Seeds()
    with pytest.raises(ValueError, match="expected seed revision changed"):
        command(Namespace(**(vars(args(reviewer="peer")) | {"if_revision": 2})), seeds)
    with pytest.raises(ValueError, match="flags require"):
        work_item.command(Namespace(item_action="show", reviewer="peer"), seeds)
    assert not seeds.writes
