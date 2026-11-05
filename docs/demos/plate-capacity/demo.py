"""Same isolated membership and P0 assignment probe on base and candidate."""
from argparse import Namespace
from contextlib import redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from shantytown.answer import Answer
from shantytown.files import FilesTracker
from shantytown.plate_capacity import PlateFull, ensure_room, size
from shantytown.sd import SdTracker
from shantytown.work_item import command


def main():
    with TemporaryDirectory(prefix='plate-demo-') as temporary:
        previous = os.environ.get('HOME')
        os.environ['HOME'] = temporary
        try:
            tracker = FilesTracker(Path(temporary) / 'items')
            work = [tracker.create(f'Work {i}', assignee='worker', priority=2) for i in range(10)]
            notes = [tracker.create(f'inbox: delivery {i}', assignee='worker') for i in range(7)]
            print('count before inbox closes:', size(tracker, 'worker'))
            for note in notes:
                tracker.update(note.id, status='closed')
            print('count after seven inbox closes:', size(tracker, 'worker'))
            ordinary = tracker.create('Ordinary work', priority=2)
            args = Namespace(item=ordinary.id, item_action='update', dry_run=False,
                             assignee='worker', status='in_progress', priority=None)
            try:
                command(args, tracker)
            except PlateFull as error:
                print('ordinary refusal names all counted IDs:', all(row.id in str(error) for row in work))
            urgent = tracker.create('Incident', priority=0)
            args.item = urgent.id
            with redirect_stderr(StringIO()):
                try:
                    command(args, tracker)
                    print('P0 assignment: admitted')
                except PlateFull:
                    print('P0 assignment: refused')
            print('P0 owner readback:', tracker.get(urgent.id).assignee)
            path = Path(temporary) / '.local/state/shantytown/plate-capacity/overflow.jsonl'
            events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
            print('overflow admission records:', len(events))
            for row in work[:3]:
                tracker.update(row.id, assignee='', status='open')
            print('count after three work repools:', size(tracker, 'worker'))

            rows = [dict(id=row.id, title='Work', assignee='worker', status='open') for row in work]
            scoped = SdTracker(quipu='https://example.invalid', prefix='fixture')
            scoped.render_shape_reads = object()
            scoped._roster_capacity = {'worker': Answer.complete_read(rows, how='frozen render')}
            scoped._use_remote_projection = lambda: False
            scoped._owner_rows = lambda owner: Answer.complete_read(rows[3:], how='current membership')
            print('frozen crew count:', size(scoped, 'worker'), '/ current owner count:', len(rows[3:]))
            try:
                ensure_room(scoped, 'worker')
                print('ordinary admission after actual work repools: admitted')
            except PlateFull:
                print('ordinary admission after actual work repools: refused')
        finally:
            if previous is None:
                os.environ.pop('HOME', None)
            else:
                os.environ['HOME'] = previous


if __name__ == '__main__':
    main()
