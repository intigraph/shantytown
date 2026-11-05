import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest
from shantytown import cost, cost_coverage


def records():
    return {'one': {'id': 'one', 'status': 'closed'},
            'two': {'id': 'two', 'status': 'closed'},
            'live': {'id': 'live', 'status': 'in_progress'}}


def test_completed_metadata_counts_not_observed_token_groups():
    value = cost_coverage.completed(records())
    assert (value['completed_seeds'], value['unknown_cost_seeds'], value['unknown_cost_share']) == (2, 2, 1)
    assert value['whole_session_item_limit'] == 8 and not value['partitions_enabled']
    assert '2/2' in cost_coverage.describe(value) and '100%' in cost_coverage.describe(value)
    assert value['global_completed_seed_coverage'] == 'UNKNOWN'


@pytest.mark.parametrize('value', [None, [], {'one': None}, {'one': {'id': 'other', 'status': 'closed'}},
                                    {'one': {'status': 'unknown'}}])
def test_unverified_cohort_never_becomes_zero_or_percent(value):
    summary = cost_coverage.completed(value)
    assert summary['completed_seeds'] is None and summary['unknown_cost_share'] is None
    assert 'UNKNOWN/UNKNOWN' in cost_coverage.describe(summary)
    assert '100%' not in cost_coverage.describe(summary)


def test_zero_and_selected_seed_are_not_global_coverage():
    empty = cost_coverage.completed({'live': records()['live']})
    assert empty['completed_seeds'] == 0 and empty['unknown_cost_share'] is None
    assert '(n/a)' in cost_coverage.describe(empty)
    assert cost_coverage.completed(records(), 'one')['completed_seeds'] == 1
    assert cost_coverage.completed(records(), 'absent')['completed_seeds'] is None


@pytest.mark.parametrize('bead,json_output', [(None, True), ('one', True), ('one', False)])
def test_real_display_has_summary_without_more_reads_or_mutating_counts(monkeypatch, bead, json_output):
    original = {'scope': 'supplied sources, not lifetime', 'groups': [], 'errors': [], 'records': []}
    saved = copy.deepcopy(original)
    calls = []
    monkeypatch.setattr(cost, 'retrieve', lambda *_: (calls.append('existing retrieval') or original, records(), {}))
    monkeypatch.setattr(cost, '_br', lambda *_: pytest.fail('new board read'))
    monkeypatch.setattr(cost, 'subprocess', SimpleNamespace(run=lambda *_: pytest.fail('new publisher/read')))
    out = io.StringIO()
    with redirect_stdout(out):
        assert cost._run_selected(SimpleNamespace(root=Path('/synthetic'), sync=False, bead=bead,
                                                  json=json_output), {}, Path('/synthetic/state')) == 0
    assert original == saved and calls == ['existing retrieval']
    if json_output:
        result = json.loads(out.getvalue())
        assert result['groups'] == [] and result['cost_coverage']['unknown_cost_share'] == 1
    else:
        assert '1/1 completed seeds (100%)' in out.getvalue()
        assert 'cost: UNKNOWN (no attributable requests)' in out.getvalue()
