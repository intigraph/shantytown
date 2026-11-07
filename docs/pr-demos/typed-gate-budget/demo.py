"""Synthetic observation-capacity demo. No network, grants or live state."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument('--expect', choices=['legacy', 'fixed'], required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source.resolve()))
from shantytown import feed_check
from shantytown.answer import Answer
from shantytown.notify import DeferralAlerter
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes

now = datetime(2026, 11, 6, 4, tzinfo=timezone.utc)
until = '2026-11-07T05:00:00Z'
rows = []
for index in range(15):
    item = f'item-{index:02}'
    kind = 'activation' if index % 2 else 'ruling'
    provenance = json.dumps(dict(actor='worker', set_at='2026-11-06T03:00:00Z', until=until))
    rows.append(dict(id=item, title='fixture', assignee='worker', priority=1,
        status='deferred', labels=['blocked:external'], defer_until=until,
        notes=f'resume_when: {kind}:{item}\ndefer_provenance: {provenance}'))
cards = [Agent('admin', role='administrator'), Agent('lead', role='lead'),
         Agent('worker', reports_to='lead')]
registry = SimpleNamespace(all=lambda: Answer.complete_read(cards, how='fixture'),
                          get=lambda name: next(card for card in cards if card.name == name))
by_id = {row['id']: row for row in rows}
seen = set()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    journal = root / 'notify/deferral-retries.json'
    journal.parent.mkdir()
    journal.write_text(json.dumps({item: 2 for item in by_id}))
    for tick in range(4):
        observed, deliveries, releases = [], [], []
        adapter = SimpleNamespace(ruling_comments=lambda item: observed.append(item) or [])
        with patch.object(feed_check, 'backend_adapter', return_value=adapter):
            DeferralAlerter(root, registry, NullPanes(), read=lambda: rows,
                show=by_id.__getitem__, now=now + timedelta(minutes=5 * tick),
                release=releases.append,
                push=lambda _r, _p, text: deliveries.append(text) or 'admin').sweep()
        retry_counts = json.loads(journal.read_text())
        assert len(observed) == 12 and not releases
        seen.update(observed)
        if tick == 0:
            count = 3 if args.expect == 'legacy' else 2
            assert len(retry_counts) == 3 and set(retry_counts.values()) == {count}
            assert len(deliveries) == (1 if args.expect == 'legacy' else 0)
            print(f'first pass: admitted={len(observed)} skipped=3 '
                  f'prior failure count=2 -> {count}; admin alerts={len(deliveries)}')
    expected = 12 if args.expect == 'legacy' else 15
    assert len(seen) == expected
    print(f'four passes: distinct gates observed={len(seen)}/15; reads/pass=12')
    print('all gates held; no activation, network request or live-state change')
