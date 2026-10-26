"""Run with the selected source checkout on PYTHONPATH; no service writes."""
import copy
from shantytown.answer import Answer
from shantytown.plate_capacity import PlateFull, ensure_room, size

class Fixture:
    def __init__(self, ordinary):
        self.rows = [dict(id=f'work-{i}', title='Implementation', assignee='worker',
                          status='open', priority=1) for i in range(ordinary)]
        self.rows += [dict(id=f'ask-{i}', title='ASK Stiwi: choose', assignee='worker',
                           status='open', labels=['desk']) for i in range(5)]
    def capacity_rows(self, owner):
        return Answer.complete_read(self.rows, how='isolated fixture')

for count in (5, 10):
    fixture = Fixture(count)
    before = copy.deepcopy(fixture.rows)
    print(f'Input: {count} ordinary work + 5 owned ASK records')
    print(f'Weighted work count: {size(fixture, "worker")}')
    try:
        ensure_room(fixture, 'worker', candidate=dict(id='new', title='Implementation', priority=1))
        print('New P1 admission: allowed')
    except PlateFull:
        print('New P1 admission: refused')
    assert fixture.rows == before
    print('All input rows, owners and statuses unchanged: yes')
