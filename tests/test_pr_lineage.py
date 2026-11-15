from copy import deepcopy

import pytest

from shantytown import pr_lineage as l
from shantytown import pr_preflight as p
from test_pr_preflight import Forge, pull, candidate, REPO, HEAD, OTHER


class LineageForge(Forge):
    def __init__(self):
        old = pull(bead="project-new")
        old["html_url"] = f"https://github.com/{REPO}/pull/1"
        super().__init__([old])
        self.events = []

    def __call__(self, path, body=None):
        if body is not None:
            self.events.append((path, deepcopy(body)))
            if path.endswith("/comments"):
                return {"id": 12}
        return super().__call__(path, body)

    def patch(self, path, body):
        self.events.append((path, body))
        self.rows[0]["state"] = "closed"
        return deepcopy(self.rows[0])


def publish(forge, **kw):
    return p.run("unused", REPO, "main", "project-new", "Replacement\n\nSupersedes: #1",
                 "Replacement", [], create=True, api=forge, patch_api=forge.patch, **kw)


def test_publish_then_pointer_then_close(candidate):
    forge = LineageForge()
    result = publish(forge)
    assert result["lineage"] == [{"number": 1, "head": OTHER, "action": "closed"}]
    assert [path for path, _ in forge.events] == [f"repos/{REPO}/pulls",
        f"repos/{REPO}/issues/1/comments", f"repos/{REPO}/pulls/1"]
    assert "/pull/99" in forge.events[1][1]["body"]


def test_dry_run_does_not_retire(candidate):
    forge = LineageForge()
    assert publish(forge, dry_run=True)["lineage"][0]["head"] == OTHER
    assert forge.events == [] and forge.rows[0]["state"] == "open"


def test_lost_create_never_retires(candidate):
    forge = LineageForge()
    forge.lost_response = True
    with pytest.raises(p.Indeterminate, match="create outcome unknown"):
        publish(forge)
    assert len(forge.events) == 1 and forge.rows[0]["state"] == "open"


def test_changed_predecessor_after_create_preserves_successor(candidate):
    forge = LineageForge()
    original = forge.__call__
    def api(path, body=None):
        result = original(path, body)
        if body is not None and path.endswith("/pulls"):
            forge.rows[0]["head"]["sha"] = "d" * 40
        return result
    with pytest.raises(p.Indeterminate, match="successor #99 exists"):
        p.run("unused", REPO, "main", "project-new", "Supersedes: #1", "New", [],
              create=True, api=api, patch_api=forge.patch)
    assert len(forge.events) == 1 and forge.rows[0]["state"] == "open"


def test_wrong_item_refuses_before_publish(candidate):
    forge = LineageForge()
    forge.rows[0]["body"] = "Bead: project-other"
    with pytest.raises(p.Refused, match="same primary"):
        publish(forge)
    assert not forge.events


@pytest.mark.parametrize("body", ["Supersedes: https://example.com/1", "Folds: #0",
    "Supersedes: #1\nFolds: #1", "Split-from: #1, #2"])
def test_malformed_or_duplicate_declarations_refuse(body):
    with pytest.raises(l.LineageError):
        l.declarations(body)


def test_code_example_is_not_authority():
    assert l.declarations("```text\nSupersedes: #1\n```\nStacked-on: #2") == [
        {"relation": "Stacked-on", "number": 2}]


def test_stack_retains_predecessor(candidate):
    forge = LineageForge()
    candidate["base"] = OTHER
    plan = l.prepare(forge, REPO, "Stacked-on: #1", "project-new", candidate)
    assert l.retire(forge, forge.patch, REPO, plan, {}, "project-new", candidate) == [
        {"number": 1, "action": "kept-open-stack"}]
    assert not forge.events


@pytest.mark.parametrize("field,value", [("head", None), ("head", {"sha": 12}),
    ("body", []), ("number", True), ("html_url", "https://example.org/pull/1")])
def test_malformed_predecessor_refuses_without_write(candidate, field, value):
    forge = LineageForge()
    forge.rows[0][field] = value
    with pytest.raises(l.LineageError):
        l.prepare(forge, REPO, "Folds: #1", "project-new", candidate)
    assert not forge.events


def test_close_lost_response_preserves_created_identity(candidate):
    forge = LineageForge()
    def patch(path, body):
        forge.patch(path, body)
        raise p.Refused("lost close response")
    with pytest.raises(p.Indeterminate, match="successor #99 exists"):
        p.run("unused", REPO, "main", "project-new", "Folds: #1", "New", [],
              create=True, api=forge, patch_api=patch)
    assert forge.rows[0]["state"] == "closed"
    assert len(forge.events) == 3
