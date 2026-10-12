"""Caller-declared read attribution; never a write actor or authorization."""
from contextlib import contextmanager
import os


@contextmanager
def declared_query_identity(name: str):
    """Scope SDK and native read headers without changing session/write identity."""
    before = os.environ.get("QUIPU_AGENT")
    os.environ["QUIPU_AGENT"] = name
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("QUIPU_AGENT", None)
        else:
            os.environ["QUIPU_AGENT"] = before
