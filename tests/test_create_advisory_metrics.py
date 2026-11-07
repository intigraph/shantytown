from datetime import datetime, timezone
import json

import pytest

from shantytown.create_advisory_metrics import coverage_report, WINDOW

NOW = 1793830000


def event(number, outcome='skipped', age=0, **extra):
    return dict(event_id=str(number), outcome=outcome,
                at=datetime.fromtimestamp(NOW-age, timezone.utc).isoformat(), **extra)


def test_window_counts_skips_separately_and_bounds_reason_labels(tmp_path):
    path = tmp_path / 'events'
    rows = [event(1, reason='configure BOBBIN_SERVER and SHANTY_CREATE_JEV_COMMAND'),
            event(2, reason='private unbounded secret must never be a metric label'),
            event(3, 'fired'), event(4, 'no-match'), event(5, age=WINDOW+1)]
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    report = coverage_report(path, now=NOW)
    assert report['log_read_ok'] and report['events'] == 4
    assert report['skipped'] == 2 and report['evaluated'] == 2
    assert report['warned'] == 1 and report['skip_ratio'] == .5
    assert report['skip_reasons'] == dict(missing_configuration=1, other=1)
    assert 'secret' not in json.dumps(report)


def test_empty_population_has_unknown_ratio_not_perfect_coverage(tmp_path):
    path = tmp_path / 'events'; path.write_text('')
    report = coverage_report(path, now=NOW)
    assert report['log_read_ok'] and report['events'] == 0
    assert report['skip_ratio'] is None and report['last_event'] is None


@pytest.mark.parametrize('rows', [None, ['not json'],
    [event(1), event(1)], [event(1, 'success')], [event(1, age=-120)]])
def test_missing_corrupt_duplicate_or_future_log_is_unknown(tmp_path, rows):
    path = tmp_path / 'events'
    if rows is not None:
        path.write_text(''.join((r if isinstance(r, str) else json.dumps(r))+'\n' for r in rows))
    report = coverage_report(path, now=NOW)
    assert not report['log_read_ok']
    assert 'skip_ratio' not in report and 'events' not in report
