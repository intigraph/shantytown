"""Before/after demo for za4f.6.1: a verified triage report becomes journaled shadow intents once."""
import copy, os, tempfile
from shantytown.incident_consumer import consume
from tests.test_incident_report import envelope, report

frozen = {'version': 1, 'item': 'item-1', 'fingerprint_kind': 'alertmanager-native',
          'fingerprint': '1234567890abcdef', 'onset_utc': '2026-11-22T04:00:00Z'}
journal = tempfile.mkdtemp(prefix='incident-journal-')
os.chmod(journal, 0o700)
spec = envelope()
first = consume(report(), frozen=frozen, jobspec=spec, journal=journal, verified=True)
print('first :', [i.action for i in first.intents], 'replay =', first.replay)
again = consume(report(), frozen=frozen, jobspec=spec, journal=journal, verified=True)
print('again :', [i.action for i in again.intents], 'replay =', again.replay, '| files =', len(os.listdir(journal)))
other = copy.deepcopy(frozen); other['fingerprint'] = 'fedcba0987654321'
print('other incident :', consume(report(), frozen=other, jobspec=spec, journal=journal, verified=True))
print('unverified     :', consume(report(), frozen=frozen, jobspec=spec, journal=journal, verified=False))
changed = report(); changed['summary'] = 'A different conclusion'
print('rebound run    :', consume(changed, frozen=frozen, jobspec=spec, journal=journal, verified=True))
print('journal files  :', len(os.listdir(journal)), '(still one)')
