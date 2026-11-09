"""Per-invocation tracker evidence; no retries, raw bodies or credentials."""
from contextvars import ContextVar
import json
import subprocess
import uuid
import re
from urllib.parse import urlsplit

_active = ContextVar("tracker_operation", default=None)


class ItemNotFound(LookupError):
    """A complete exact-ID observation had no facts for the requested item."""


def active():
    return _active.get() is not None


def safe_graph(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme and not (parsed.username or parsed.password or parsed.query) else None
    except ValueError:
        return None


def phase(value):
    operation = _active.get()
    if operation is not None:
        operation.phase = value


def observe(result):
    operation = _active.get()
    if operation is not None and result.returncode:
        operation.upstream_exit = result.returncode
        try:
            value = json.loads(result.stdout)
            error = value.get("error", {})
            if isinstance(error, dict):
                operation.upstream_code = error.get("code")
                details = error.get("details")
                if isinstance(details, dict):
                    operation.http_status = details.get("http_status")
                    if details.get("category") in ("MALFORMED_RESPONSE", "PARTIAL", "TIMEOUT"):
                        operation.original_category = details["category"]
        except (ValueError, TypeError, AttributeError):
            pass


def timed_out():
    operation = _active.get()
    if operation is not None:
        operation.original_category = "TIMEOUT"


class Operation:
    def __init__(self, args):
        self.operation_id = uuid.uuid4().hex
        self.args = args
        self.phase = "READ"
        self.upstream_exit = None
        self.upstream_code = None
        self.http_status = None
        self.graph = None
        self.original_category = None

    def __enter__(self):
        self.token = _active.set(self)
        return self

    def __exit__(self, *exc):
        _active.reset(self.token)

    def result(self, data=None, error=None):
        writes = self.args.item_action != "show" and not self.args.dry_run
        code = 0
        category = None
        native = self.upstream_code
        status = self.http_status
        if error is not None:
            if native is None:
                native = getattr(error, "code", None)
            if not isinstance(native, str) or native not in {"FAILED", "USAGE", "NOT_FOUND", "CONFLICT", "REFUSED",
                    "CONFIG", "UNREACHABLE", "INDETERMINATE", "NOT_BUILT", "ELSEWHERE"}:
                native = "UNKNOWN"
            status = status or getattr(error, "status", None)
            # HTTPError.code is numeric; it is not a tracker error code.
            http_code = getattr(error, "code", None)
            if isinstance(http_code, int):
                status = http_code
            if type(status) is not int:
                status = None
            category = self.original_category or {401:"AUTH",403:"POLICY",408:"TIMEOUT"}.get(status)
            category = category or {"USAGE":"VALIDATION", "NOT_FOUND":"NOT_FOUND",
                "CONFLICT":"CONFLICT", "REFUSED":"POLICY", "CONFIG":"CONFIG",
                "UNREACHABLE":"TRANSPORT", "INDETERMINATE":"INDETERMINATE"}.get(native)
            if category is None:
                category = ("NOT_FOUND" if isinstance(error, ItemNotFound)
                    else "MISSING_INPUT" if isinstance(error, FileNotFoundError)
                    else "MALFORMED_RESPONSE" if isinstance(error, json.JSONDecodeError)
                    else "TIMEOUT" if isinstance(error, (TimeoutError, subprocess.TimeoutExpired))
                    else "VALIDATION" if isinstance(error, ValueError)
                    else "TRANSPORT" if isinstance(error, ConnectionError) or status
                    else "UNKNOWN")
            code = self.upstream_exit or (3 if isinstance(error, ItemNotFound) else {"CONFLICT":4,"INDETERMINATE":8}.get(native, 2))
        outcome = ("NOT_APPLICABLE" if not writes else "COMMITTED" if error is None
            else "NOT_WRITTEN" if self.phase in {"READ", "INPUT"} else "UNKNOWN")
        if error is not None and type(error).__name__ == "NothingWritten":
            outcome = "NOT_WRITTEN"
        return {"schema":"tracker-result/v1", "ok":error is None,
            "operation_id":self.operation_id, "operation":self.args.item_action,
            "tasks":[self.args.item] if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", self.args.item) else [], "graph":safe_graph(self.graph),
            "phase":self.phase, "mutation_outcome":outcome, "exit_code":code,
            "data":data if error is None else None,
            "error":None if error is None else {"category":category,"code":native,
                "http_status":status if isinstance(status,int) else None,
                "message":"Operation failed; private diagnostics omitted"},
            "reconcile":"Read exact task status and operation evidence before any retry; never replay a comment blindly"
                if writes and error is not None else "No automatic retry or store/credential change"}
