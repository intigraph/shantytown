"""Identical isolated admission probe for a malformed top-level label map."""
from shantytown.answer import Answer
from shantytown.plate_capacity import PlateFull, ensure_room, size

class Rows:
    def __init__(self, labels):
        self.rows = [dict(id=f'work-{i}', title='Ordinary work', labels=labels,
                          assignee='worker', status='open', priority=1) for i in range(10)]
    def capacity_rows(self, owner):
        return Answer.complete_read(self.rows, how='isolated complete owner fixture')

for title, labels, candidate_labels in [
    ('Ten owned rows with labels={"desk": false}', {'desk': False}, []),
    ('Ten ordinary rows; incoming candidate has labels={"desk": false}', [], {'desk': False}),
]:
    tracker = Rows(labels)
    print(title)
    print(f'Counted work: {size(tracker, "worker")}')
    try:
        ensure_room(tracker, 'worker', candidate=dict(title='Ordinary incoming work',
                                                    priority=1, labels=candidate_labels))
        print('New P1 admission: allowed')
    except PlateFull:
        print('New P1 admission: refused')
