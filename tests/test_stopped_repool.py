from contextlib import nullcontext
import copy
import unittest

from shantytown.stopped_repool import candidates, repool


def item(**kw):
    row = dict(id='work-1', title='Implement detector', assignee='stopped',
               status='in_progress', priority=0, labels=[], revision=4)
    row.update(kw)
    return row


class StoppedRepool(unittest.TestCase):
    def run_detector(self, row=None, *, age=1800, state='stopped', dry=False, race=None, fail=False):
        row = row or item()
        rows = {row['id']: copy.deepcopy(row)}
        evidence = {'stopped': {'state': state, 'since': 0}}
        writes, journal, saved = [], {}, []
        def release(current, comment, **kw):
            writes.append((current, comment))
            if fail:
                raise RuntimeError('unknown remote write')
            rows[current['id']].update(status='open', assignee='', comments=[{'text': comment}])
            return 'released'
        args = dict(read=lambda identity: rows[identity], release=release,
                    observe=lambda name: race or evidence[name], fence=lambda name: nullcontext(),
                    journal=journal, save=lambda j: saved.append(copy.deepcopy(j)), now=age, dry_run=dry)
        result = repool([row], evidence, **args)
        return result, writes, rows, args, journal

    def test_stopped_work_repooled_with_named_comment(self):
        result, writes, rows, _, _ = self.run_detector()
        self.assertEqual(result, [('work-1', 'released')])
        self.assertEqual(rows['work-1']['status'], 'open')
        self.assertFalse(rows['work-1']['assignee'])
        self.assertIn('stopped holder stopped', writes[0][1])

    def test_live_below_threshold_ask_and_inbox_never_released(self):
        for changes in [dict(state='live'), dict(age=1799),
                        dict(row=item(title='ASK Stiwi: choose')),
                        dict(row=item(labels=['needs-stiwi']))]:
            with self.subTest(changes=changes):
                self.assertEqual(self.run_detector(**changes)[1], [])

    def test_urgent_owner_threshold_applies_to_lower_priority_work(self):
        urgent, low = item(), item(priority=3, id='work-2')
        self.assertEqual(len(candidates([urgent, low],
                         {'stopped': {'state': 'held', 'since': 0}}, 1800)), 2)

    def test_inbox_pointer_is_flagged_and_never_released(self):
        row = item(title='inbox: message')
        result, writes, _, _, _ = self.run_detector(row)
        self.assertEqual(writes, [])
        self.assertIn('not delivered work', result[0][1])

    def test_four_hour_lower_priority_boundary(self):
        row = item(priority=2)
        self.assertEqual(self.run_detector(row, age=14399)[1], [])
        self.assertEqual(len(self.run_detector(row, age=14400)[1]), 1)

    def test_dry_run_no_remote_or_journal_writes(self):
        result, writes, rows, _, journal = self.run_detector(dry=True)
        self.assertEqual(result, [('work-1', 'would repool from stopped to open/unassigned')])
        self.assertEqual(writes, [])
        self.assertEqual(journal, {})
        self.assertEqual(rows['work-1']['assignee'], 'stopped')

    def test_relaunch_race_refuses_release(self):
        self.assertEqual(self.run_detector(race={'state': 'live'})[1], [])

    def test_unknown_intent_never_repeats_write(self):
        row = item()
        journal = {'work-1': {'comment': 'retained intent'}}
        calls = []
        result = repool([row], {'stopped': {'state': 'stopped', 'since': 0}},
                        read=lambda _: row, release=lambda *a, **k: calls.append(a),
                        observe=lambda _: {}, fence=lambda _: nullcontext(), journal=journal,
                        save=lambda _: self.fail('unexpected save'), now=1800)
        self.assertEqual(calls, [])
        self.assertIn('UNKNOWN', result[0][1])


if __name__ == '__main__':
    unittest.main()

class AdapterDryRun(unittest.TestCase):
    def test_dry_run_uses_stop_age_without_creating_state_or_mutating_tracker(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from shantytown.answer import Answer
        from shantytown.stopped import FilesStops
        from shantytown.stopped_repool import sweep
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            FilesStops(root/'stopped').record('stopped', 0)
            card = SimpleNamespace(name='stopped', host='fixture', pane='fixture-pane')
            registry = Mock()
            registry.all.return_value = Answer.complete_read([card], how='fixture')
            registry.get.return_value = card
            tracker, panes = Mock(), Mock()
            tracker.stranded_rows.return_value = [item()]
            panes.owner_state.return_value = 'down'
            with patch('shantytown.deployment.local_host', return_value='fixture'):
                result = sweep(root, registry, tracker, panes, now=1800, dry_run=True)
            self.assertIn('would repool', result[0][1])
            self.assertFalse((root/'stopped-repool').exists())
            tracker.release_stranded.assert_not_called()
            tracker.stranded_read.assert_not_called()
