"""Regression guards for the closed attended Action request boundary."""
import copy
import sys

import pytest

from test_job_review import job  # noqa: F401
from test_review_enqueue import custody  # noqa: F401
from test_attended_enqueue_adapter import prepared  # noqa: F401
from shantytown import review_enqueue_attended as adapter

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'),
                                reason='Linux directory-FD custody backend')


@pytest.mark.parametrize('fault', ['extra-field', 'schema', 'intent', 'attempt',
                                  'authority', 'boolean-pr'])
def test_attended_action_guard_refuses_unbound_request_before_native(prepared, fault):
    request = copy.deepcopy(prepared.request)
    if fault == 'extra-field': request['checkout'] = '/reviewer/chosen'
    elif fault == 'schema': request['schema'] = 'another-action/v1'
    elif fault == 'intent': request['intent'] = '0' * 64
    elif fault == 'attempt': request['attempt'] = 'not-a-digest'
    elif fault == 'authority': request['candidate']['authority'] = 'https://other.invalid'
    elif fault == 'boolean-pr': request['candidate']['pr'] = True
    with pytest.raises((adapter.IdentityError, ValueError)):
        adapter.execute(request, root=prepared.root, native=prepared.native,
                        quipu=prepared.q, run=prepared.run)
    assert prepared.calls == []
    assert not list((prepared.base / 'bindings').glob('*.prepare.json'))
