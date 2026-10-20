import copy
from datetime import datetime, timedelta, timezone
import unittest
from consume import join


def fixture():
    start = datetime(2026, 9, 16, tzinfo=timezone.utc)
    captured = datetime(2026, 10, 16, 12, tzinfo=timezone.utc).timestamp()
    identities = {'schema_version': 1, 'agents': [{'label': a, 'iri': f'urn:example:agent:{a}'} for a in ('alpha', 'beta')]}
    daily = {'schema_version': 1, 'semantics': 'event_day_usage', 'sessions': []}
    closed = {'schema_version': 1, 'semantics': 'retained_close_current_assignee',
              'start': '2026-09-16', 'end_exclusive': '2026-10-16',
              'truncated': False, 'graph_visible': True, 'distinct_control': 0, 'rows': [],
              'source': {'graph_iri': 'urn:example:graph:work', 'query_sha256': '0' * 64,
                         'captured_at': '2026-10-16T12:00:00Z'}}
    for agent in ('alpha', 'beta'):
        rows = []
        for n in range(30):
            at = start + timedelta(days=n)
            counts = dict(input_uncached=4, cache_read_input=3, cache_write_input=2,
                          output=None if agent == 'beta' and n == 7 else n * 10)
            rows.append(dict(day=str(at.date()), agent=agent, rig='example', seed='seed-a',
                             model='model', harness='codex', counts=counts))
            for i in range(n % 3):
                closed['rows'].append(dict(item_iri=f'urn:example:seed:{agent}-{n}-{i}',
                    agent_iri=f'urn:example:agent:{agent}', closed_at=at.isoformat()))
        daily['sessions'].append({'source': {'agent': agent, 'harness': 'codex', 'session': agent},
                                  'captured_at': captured, 'receipt': 'synthetic', 'rows': rows})
    closed['distinct_control'] = len(closed['rows'])
    return daily, closed, identities


class Consumer(unittest.TestCase):
    def test_four_kinds_thirty_day_oracle(self):
        answer = join(*fixture(), '2026-10-16')
        self.assertEqual(len(answer['rows']), 240)
        for row in answer['rows']:
            n = (datetime.fromisoformat(row['day']).date() - datetime(2026, 9, 16).date()).days
            expected = {'input_uncached': 4, 'cache_read_input': 3, 'cache_write_input': 2,
                        'output': None if row['agent_iri'].endswith(':beta') and n == 7 else n * 10}
            self.assertEqual(row['tokens_observed'], expected[row['kind']])
            self.assertFalse(row['usage_day_complete'])
            self.assertEqual(row['retained_closes_current_assignee'], n % 3)

    def test_actual_worker_refuses_external_sql_read(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import duckdb
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'control.txt'
            path.write_text('source-control')
            control = duckdb.connect(':memory:')
            try:
                self.assertEqual(control.execute('SELECT content FROM read_text(?)', [str(path)]).fetchone()[0], 'source-control')
            finally:
                control.close()
            with patch('consume.Path.read_text', return_value='SELECT * FROM read_text(' + repr(str(path)) + ')'):
                with self.assertRaises(duckdb.Error):
                    join(*fixture(), '2026-10-16')

    def test_missing_usage_stays_unknown(self):
        daily, closed, identities = fixture()
        daily['sessions'] = []
        rows = join(daily, closed, identities, '2026-10-16')['rows']
        self.assertTrue(all(r['tokens_observed'] is None and not r['usage_day_complete'] for r in rows))

    def test_refuse_uncertain_sources_before_sql(self):
        mutations = [
            lambda d, c, i: c.update(truncated=True),
            lambda d, c, i: c.update(graph_visible=False),
            lambda d, c, i: c.update(distinct_control=0),
            lambda d, c, i: c.update(start='2026-09-15'),
            lambda d, c, i: c.update(source={}),
            lambda d, c, i: d.update(semantics='corrective_gauge'),
            lambda d, c, i: d['sessions'].append(copy.deepcopy(d['sessions'][0])),
            lambda d, c, i: d['sessions'][0]['rows'].append(copy.deepcopy(d['sessions'][0]['rows'][0])),
            lambda d, c, i: i['agents'][0].update(iri='guessed-label'),
            lambda d, c, i: d['sessions'][0]['source'].update(agent='different'),
        ]
        for mutate in mutations:
            inputs = fixture(); mutate(*inputs)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                join(*inputs, '2026-10-16')


if __name__ == '__main__':
    unittest.main()
