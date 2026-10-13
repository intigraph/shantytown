"""Caller-declared read attribution; never a write actor or authorization."""
from contextlib import contextmanager
from contextvars import ContextVar
import os

_caller = ContextVar("query_caller", default=None)


def current_query_identity():
    return _caller.get()


def sdk_subprocess_options():
    """Give only SDK children the declared caller; agent launches stay untouched."""
    name = current_query_identity()
    return {"env": dict(os.environ, QUIPU_AGENT=name)} if name else {}


@contextmanager
def declared_query_identity(name: str):
    token = _caller.set(name)
    try:
        yield
    finally:
        _caller.reset(token)
