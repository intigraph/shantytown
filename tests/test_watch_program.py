"""Watch content proofs stay separate from activation and release authority."""
from dataclasses import FrozenInstanceError
import math
import pytest
from shantytown.watch_program import Observation, WatchRefused, WatchSpec, evaluate_watch, next_sample_at


@pytest.fixture
def raw():
    return dict(version=1, run_id='fixture-run', source_digest='a' * 64,
                deployment_receipt='fixture-native-receipt', identity='frozen-sha-pid-config',
                start=1000, window_seconds=100, sample_seconds=45,
                maximum={'p99_seconds': 6.4875, 'error_fraction': .01})


@pytest.fixture
def spec(raw):
    return WatchSpec.validate(raw)


def samples(spec, **changes):
    return [Observation(at, spec.identity, dict(p99_seconds=1.56, error_fraction=.0011, **changes))
            for at in spec.grid()]


def test_terminal_sample_is_not_lost_when_cadence_does_not_divide_window(spec):
    assert spec.grid() == (1000, 1045, 1090, 1100)
    at = None; observed = []
    while (at := next_sample_at(spec, at)) is not None:
        observed.append(at)
    assert tuple(observed) == spec.grid()
    assert next_sample_at(spec, 1090) == 1100


def test_restart_continues_original_grid_without_resetting_clock(spec):
    assert next_sample_at(spec, 1045) == 1090
    with pytest.raises(WatchRefused): next_sample_at(spec, 1046)


def test_safety_pass_does_not_credit_config_true_but_native_inactive(spec):
    result = evaluate_watch(spec, samples(spec), now=1100, activation='INACTIVE')
    assert (result.safety, result.activation, result.improvement) == ('PASS', 'INACTIVE', 'NOT_EVALUATED')
    assert result.compensation == 'NOT_EXECUTED'


def test_safety_pass_does_not_invent_improvement_or_authority(spec):
    result = evaluate_watch(spec, samples(spec), now=1100, activation='ACTIVE')
    assert (result.safety, result.improvement, result.compensation) == ('PASS', 'UNKNOWN', 'NOT_EXECUTED')


@pytest.mark.parametrize('comparison,comparable,expected', [
    ((2., 1.), True, 'IMPROVED'), ((1., 1.), True, 'NO_IMPROVEMENT'),
    ((1., 2.), True, 'NO_IMPROVEMENT'), ((2., 1.), False, 'UNKNOWN'),
    ((0., 0.), True, 'UNKNOWN'), ((math.nan, 1.), True, 'UNKNOWN')])
def test_comparison_needs_positive_finite_admitted_cohorts(spec, comparison, comparable, expected):
    assert evaluate_watch(spec, samples(spec), now=1100, activation='ACTIVE',
                          comparison=comparison, comparable=comparable).improvement == expected


@pytest.mark.parametrize('mutation', ['tail', 'middle', 'duplicate', 'reorder', 'nan', 'missing_metric', 'future'])
def test_partial_or_invalid_evidence_cannot_pass(spec, mutation):
    rows = samples(spec); now = 1100
    if mutation == 'tail': rows.pop()
    elif mutation == 'middle': rows.pop(1)
    elif mutation == 'duplicate': rows[1] = rows[0]
    elif mutation == 'reorder': rows[1], rows[2] = rows[2], rows[1]
    elif mutation == 'nan': rows[0].metrics['p99_seconds'] = math.nan
    elif mutation == 'missing_metric': del rows[0].metrics['error_fraction']
    elif mutation == 'future': now = 1099
    result = evaluate_watch(spec, rows, now=now, activation='ACTIVE')
    assert result.safety in ('UNKNOWN', 'OBSERVING')
    assert result.improvement == 'NOT_EVALUATED'


def test_identity_change_supersedes_the_run_instead_of_averaging_it(spec):
    rows = samples(spec); rows[1] = Observation(1045, 'new-pid', rows[1].metrics)
    assert evaluate_watch(spec, rows, now=1100, activation='ACTIVE').safety == 'SUPERSEDED'


def test_real_breach_is_preserved_when_another_metric_is_missing(spec):
    rows = samples(spec); rows[0].metrics['p99_seconds'] = 8.; del rows[0].metrics['error_fraction']
    result = evaluate_watch(spec, rows, now=1100, activation='ACTIVE')
    assert result.safety == 'BREACH'
    assert result.compensation == 'NOT_EXECUTED'


def test_equal_threshold_is_allowed_and_fraction_is_not_percentage_points(spec):
    rows = [Observation(t, spec.identity, {'p99_seconds': 6.4875, 'error_fraction': .01}) for t in spec.grid()]
    assert evaluate_watch(spec, rows, now=1100, activation='ACTIVE').safety == 'PASS'
    rows[0].metrics['error_fraction'] = .01001
    assert evaluate_watch(spec, rows, now=1100, activation='ACTIVE').safety == 'BREACH'


@pytest.mark.parametrize('field,value', [('version', True), ('version', 2), ('extra', 1),
    ('source_digest', ''), ('deployment_receipt', ''), ('sample_seconds', True),
    ('window_seconds', 86401), ('sample_seconds', 0), ('maximum', {}),
    ('maximum', {'p99_seconds': math.nan}), ('maximum', {'p99_seconds': True})])
def test_invalid_specs_refuse_before_evaluation(raw, field, value):
    raw[field] = value
    with pytest.raises(WatchRefused): WatchSpec.validate(raw)


def test_spec_copies_limits_and_is_frozen(raw):
    spec = WatchSpec.validate(raw); raw['maximum']['p99_seconds'] = 999
    assert dict(spec.maximum)['p99_seconds'] == 6.4875
    with pytest.raises(FrozenInstanceError): spec.start = 2000


def test_no_samples_and_bad_clock_cannot_pass(spec):
    assert evaluate_watch(spec, [], now=1100, activation='UNKNOWN').safety == 'UNKNOWN'
    assert evaluate_watch(spec, samples(spec), now=math.nan, activation='ACTIVE').safety == 'UNKNOWN'


def test_reason_order_is_independent_of_metric_insertion_order(spec):
    rows_a = [Observation(t, spec.identity, {'p99_seconds': 8., 'error_fraction': .02}) for t in spec.grid()]
    rows_b = [Observation(t, spec.identity, {'error_fraction': .02, 'p99_seconds': 8.}) for t in spec.grid()]
    assert evaluate_watch(spec, rows_a, now=1100, activation='ACTIVE') == evaluate_watch(
        spec, rows_b, now=1100, activation='ACTIVE')


def test_sample_and_probe_cardinality_limits_refuse_without_collection(raw):
    raw.update(window_seconds=86400, sample_seconds=1)
    with pytest.raises(WatchRefused, match='sample count'): WatchSpec.validate(raw)
    raw.update(window_seconds=100, sample_seconds=45, maximum={f'm{i}': 1 for i in range(33)})
    with pytest.raises(WatchRefused, match='bounded nonempty'): WatchSpec.validate(raw)
