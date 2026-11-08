"""Isolated source demo; never reads or modifies a live producer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown import deferrals, resume_producers
from shantytown.deferral_notes import provenance

BASE = '9b08512c078632eb54406fd1d6027aeb9f800fc1'
source = subprocess.check_output(['git', 'show', BASE+':shantytown/deferrals.py'], text=True)
baseline = types.ModuleType('baseline_deferrals')
sys.modules[baseline.__name__] = baseline
exec(compile(source, 'baseline_deferrals.py', 'exec'), baseline.__dict__)
identifier = '0123456789abcdef01234567'
now = datetime(2026, 11, 8, 18, tzinfo=timezone.utc)
row = dict(id='fixture-1', notes='resume_when: recurring-quiet:'+identifier+'\n'+provenance(
    'fixture-owner', '2026-11-08T17:00:00Z', '2026-11-09T18:00:00Z'))
print('Synthetic fixture; source checkout only; no installed acceptance.')
print('base', BASE, 'head', subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
print('same marker before: testable =', baseline.parse_condition(row['notes']).testable())
print('same marker after:  testable =', deferrals.parse_condition(row['notes']).testable())
old_home = os.environ.get('HOME')
try:
    with tempfile.TemporaryDirectory(prefix='producer-resume-demo-') as directory:
        os.environ['HOME'] = directory
        path = Path(directory)/'.local/state/recurring-alarms/state.json'
        path.parent.mkdir(parents=True, mode=0o700)
        data = dict(version=1, last_census=now.timestamp(), classes={identifier:dict(
            bead='fixture-1', active=False, last_fired=(now-timedelta(days=15)).timestamp(),
            quiet_since=(now-timedelta(days=1)).timestamp())})
        def show(label, expected):
            path.write_text(json.dumps(data)); path.chmod(0o600)
            result = resume_producers.evaluate('recurring-quiet', identifier, row, now)
            print(label+':', result.state)
            assert result.state == expected
        show('one quiet day', 'NOT_MET')
        data['classes'][identifier]['quiet_since'] = (now-timedelta(days=14)).timestamp()
        show('14 authoritative quiet days', 'MET')
        data['last_census'] = 0
        show('unavailable census', 'UNKNOWN')
finally:
    if old_home is None: os.environ.pop('HOME', None)
    else: os.environ['HOME'] = old_home
