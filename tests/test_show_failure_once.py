"""Unavailable exact reads retain diagnostics without an automatic retry."""
import json
import subprocess

import pytest
from shantytown import br


class Tracker:
    repo = "primary"

    def __init__(self, results):
        self.results = results
        self.repos = list(results)
        self.calls = []

    def _bd(self, *args):
        return self._bd_in(self.repo, *args)

    def _bd_in(self, repo, *args):
        self.calls.append((repo, args))
        code, row, error = self.results[repo]
        return subprocess.CompletedProcess(args, code, json.dumps(row), error)


def test_unavailable_read_attempts_each_store_once_and_keeps_diagnostics():
    tracker = Tracker({"primary": (2, None, "HTTP408 primary"),
                       "extra": (2, None, "HTTP408 extra")})
    with pytest.raises(RuntimeError, match="HTTP408 primary; HTTP408 extra"):
        br.show(tracker, "test-exact")
    assert [repo for repo, _ in tracker.calls] == ["primary", "extra"]


def test_next_independent_read_is_fresh_after_failure():
    tracker = Tracker({"primary": (2, None, "HTTP408")})
    with pytest.raises(RuntimeError, match="HTTP408"):
        br.show(tracker, "test-exact")
    row = {"id": "test-exact", "description": "newly readable", "dependencies": []}
    tracker.results["primary"] = (0, row, "")
    assert br.show(tracker, "test-exact") == row
    assert len(tracker.calls) == 2


def test_primary_success_keeps_full_row_and_does_not_read_extra():
    row = {"id": "test-exact", "description": "retained", "dependencies": [{"id": "blocker"}]}
    tracker = Tracker({"primary": (0, row, ""), "extra": (2, None, "unavailable")})
    assert br.show(tracker, "test-exact") == row
    assert len(tracker.calls) == 1


def test_foreign_primary_id_does_not_mask_exact_extra_match():
    row = {"id": "test-exact", "description": "extra item"}
    tracker = Tracker({"primary": (0, {"id": "test-other"}, ""), "extra": (0, row, "")})
    assert br.show(tracker, "test-exact") == row
    assert [repo for repo, _ in tracker.calls] == ["primary", "extra"]


def test_foreign_only_answer_is_not_an_exact_success_or_a_reason_to_retry():
    tracker = Tracker({"primary": (0, {"id": "test-other"}, "")})
    with pytest.raises(RuntimeError, match="no exact match"):
        br.show(tracker, "test-exact")
    assert len(tracker.calls) == 1


def test_empty_failure_diagnostic_names_original_exit():
    tracker = Tracker({"primary": (7, None, "")})
    with pytest.raises(RuntimeError, match="show exited 7"):
        br.show(tracker, "test-exact")
    assert len(tracker.calls) == 1
