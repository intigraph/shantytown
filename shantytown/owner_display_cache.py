"""Share complete owner projections only in an explicitly stale display scope."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import os

from .answer import Answer
from . import seeds_read_cache as cache
from .seeds_read_flight import coalesce, SharedReadFailed


_DISPLAY = ContextVar('owner_display_read', default=False)


@contextmanager
def display_reads():
    token = _DISPLAY.set(True)
    try:
        with cache.stale_ok():
            yield
    finally:
        _DISPLAY.reset(token)


class _Incomplete(Exception):
    def __init__(self, answer):
        self.answer = answer


def shared_owner_display(shape_type):
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def read(*args, **kwargs):
            if not _DISPLAY.get():
                return function(*args, **kwargs)
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            options = dict(bound.arguments)
            proof = options.pop('proof')
            shape = options.pop('shape_reads')
            # Only the fused roster guard is independent of a render's prior
            # shape observations. Arbitrary injected guards always execute.
            if shape is not None and not (type(shape) is shape_type
                    and shape.inline_roster and options.get('plate_owners') is not None):
                return function(*args, **kwargs)
            parts = ['owner-display-v1', proof.quipu_url, proof.graph,
                     {k: options[k] for k in sorted(options)},
                     {k: v for k, v in sorted(os.environ.items()) if k.startswith('ST_')}]

            def validate(value):
                if (not isinstance(value, dict) or value.get('complete') is not True
                        or not isinstance(value.get('rows'), list)
                        or not all(isinstance(row, dict) for row in value['rows'])
                        or not isinstance(value.get('how'), str) or not value['how']):
                    raise ValueError('invalid complete owner display')
                return value

            def lookup():
                return cache.stale_lookup(parts, validate, owner_display=True)

            hit, publish = lookup()
            if hit is None and publish is None:
                return function(*args, **kwargs)

            def fetch():
                result = function(*args, **kwargs)
                if not result.complete:
                    raise _Incomplete(result)
                return dict(complete=True, rows=result.exact(), how=result.how)

            try:
                if hit is None:
                    hit = coalesce(cache._directory(), parts, options['timeout'],
                                   lookup=lookup, fetch=fetch)
                return Answer.complete_read(hit['rows'], how=(
                    'bounded-staleness owner display; ' + hit['how']))
            except _Incomplete as error:
                return error.answer
            except (SharedReadFailed, OSError, ValueError) as error:
                return Answer.capped([], how='shared owner display', caveat=str(error))
        return read
    return decorate
