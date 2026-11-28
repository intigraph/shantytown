"""Before/after demo for za4f.6.1: a replayed incident_report event becomes journaled shadow intents once."""
import copy, os, pathlib, tempfile
from shantytown.incident_consumer import consume, consume_event
from tests.test_incident_report import envelope, report

event = pathlib.Path('tests/fixtures/incident_consumer/triage-event.json').read_bytes()
frozen = {'version': 1, 'item': 'item-1', 'fingerprint_kind': 'alertmanager-native',
          'fingerprint': '1234567890abcdef', 'onset_utc': '2026-11-22T04:00:00Z'}
journal = tempfile.mkdtemp(prefix='incident-journal-')
os.chmod(journal, 0o700)
intents = lambda: [f for f in os.listdir(journal) if not f.startswith('refusal-')]
refusals = lambda: [f for f in os.listdir(journal) if f.startswith('refusal-')]
spec = envelope()
first = consume_event(event, frozen=frozen, jobspec=spec, journal=journal, verified=True)
print('event        :', [i.action for i in first.intents], 'replay =', first.replay)
again = consume_event(event, frozen=frozen, jobspec=spec, journal=journal, verified=True)
print('replayed     :', [i.action for i in again.intents], 'replay =', again.replay, '| intent files =', len(intents()))
other = copy.deepcopy(frozen); other['fingerprint'] = 'fedcba0987654321'
print('other incident :', consume(report(), frozen=other, jobspec=spec, journal=journal, verified=True))
print('unverified     :', consume(report(), frozen=frozen, jobspec=spec, journal=journal, verified=False))
print('unverified x2  :', consume(report(), frozen=frozen, jobspec=spec, journal=journal, verified=False))
changed = report(); changed['summary'] = 'A different conclusion'
print('rebound run    :', consume(changed, frozen=frozen, jobspec=spec, journal=journal, verified=True))
import json; forged = json.loads(event); forged['jobspec']['resolved']['on']['diagnosed'] = ['notify-owner']
print('forged spec    :', consume_event(json.dumps(forged).encode(), frozen=frozen, jobspec=spec, journal=journal, verified=True))
print('garbage event  :', consume_event(b'not json', frozen=frozen, jobspec=spec, journal=journal, verified=True))
print('intent files   :', len(intents()), '(still one) | refusal records :', len(refusals()), '(one per distinct refusal)')
