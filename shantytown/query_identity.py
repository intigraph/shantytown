"""Caller-declared read context, separate from components and write actors."""
from contextlib import contextmanager
import contextvars
from contextvars import ContextVar
import os
import re
from .host_identity import physical_hostname

_command = ContextVar("query_command", default=None)
_caller = ContextVar("query_caller", default=None)
_source = ContextVar("query_source", default="shantytown")
_operation = ContextVar("query_operation", default="query")


def current_query_identity():
    return _caller.get()


def _value(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= 128 and all(32 <= ord(c) <= 126 for c in value) else None


def _key(value):
    value = _value(value)
    return value.lower() if value and len(value) <= 64 and re.fullmatch(r"[A-Za-z0-9._-]+", value) else None


def _host():
    # A malformed explicit declaration remains UNKNOWN rather than silently
    # becoming a different host. This is attribution, never authentication.
    if "QUIPU_HOST" in os.environ:
        return _key(os.environ["QUIPU_HOST"])
    try:
        return _key(physical_hostname())
    except OSError:
        return None


def read_context():
    """Resolve known declarations without guessing identity from an owner/actor."""
    env = os.environ
    in_session = env.get("CLAUDECODE") == "1" or bool(env.get("CODEX_HOME"))
    caller = _value(next((v for v in (
        env.get("QUIPU_AGENT"), current_query_identity(), env.get("SEEDS_AGENT_NAME"),
        env.get("SHANTY_AGENT") if in_session else None,
    ) if v), None))
    session = _value(env.get("QUIPU_SESSION")) or _value(env.get("SEEDS_SESSION"))
    if not session:
        session = (_value(env.get("CODEX_SESSION_ID")) or _value(env.get("CODEX_THREAD_ID"))
                   if env.get("CODEX_HOME") and env.get("CLAUDECODE") != "1"
                   else _value(env.get("CLAUDE_CODE_SESSION_ID")) if in_session else None)
    # Invalid explicit task is omitted, never transformed into another identity.
    task = _key(env.get("QUIPU_TASK") if env.get("QUIPU_TASK") else env.get("SEEDS_TASK"))
    return {k: v for k, v in {
        "QUIPU_AGENT": caller, "QUIPU_SESSION": session, "QUIPU_TASK": task,
        "QUIPU_HOST": _host(),
        "QUIPU_SOURCE": _command.get() or _key(env.get("QUIPU_SOURCE")) or _source.get(),
        "QUIPU_OPERATION": _key(env.get("QUIPU_OPERATION")) or _operation.get(),
        # aegis-jve/69x: scheduling class only; can only LOWER priority.
        "QUIPU_PRIORITY": "background" if (env.get("QUIPU_PRIORITY") or "").strip().lower() == "background" else None,
    }.items() if v is not None}


def read_headers():
    return {"X-Quipu-" + key.removeprefix("QUIPU_").title(): value
            for key, value in read_context().items()}


def sdk_subprocess_options(*, read_operation=None):
    """Scope read metadata to the SDK child; retain legacy write provenance."""
    if read_operation is not None:
        with declared_query_identity(current_query_identity(), operation=read_operation):
            return {"env": dict(os.environ, **read_context())}
    name = current_query_identity() or (_source.get() if _source.get() == "st-tend" else None)
    env = dict(os.environ, QUIPU_AGENT=name) if name else None
    if _command.get():
        env = dict(env or os.environ, QUIPU_SOURCE=_command.get())
    return {"env": env} if env is not None else {}


@contextmanager
def declared_query_identity(name, *, source=None, operation=None):
    tokens = [(_caller, _caller.set(name))]
    for variable, value in ((_source, source), (_operation, operation)):
        if value is not None:
            tokens.append((variable, variable.set(_key(value) or "unknown")))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


@contextmanager
def declared_read_operation(operation):
    """Name a finite reader operation without replacing its caller or source."""
    token = _operation.set(_key(operation) or "unknown")
    try:
        yield
    finally:
        _operation.reset(token)


#: Labels that predate group-leaf labels. They stay exactly as they were:
#: quipu filters and alerts already key on them (aegis-jve).
KNOWN_COMMANDS = frozenset({"anchor", "plate", "inbox", "stop_policy", "stop_event",
                            "haul", "tend", "work", "crew", "crewid", "task", "events",
                            "harness", "stats", "go", "status", "census"})

#: The finite shape quipu admits for an st source (aegis-z29i):
#: st-[a-z][a-z_-]{0,30}.
_LABEL = re.compile(r"[a-z][a-z_-]{0,30}")


def command_label(command, group=None, *, registered=False):
    """The finite source label for one st command, never free text.

    A known leaf keeps its historical label. Otherwise a REGISTERED verb (the
    CLI passes only argparse-validated names) becomes "<group>-<leaf>", e.g.
    `st work item show` -> "work-item" and `st fleet hold` -> "fleet-hold",
    where it used to collapse into "other" and hid the P0 caller (aegis-z29i).
    Anything unregistered or outside the bounded shape stays "other".
    """
    if command in KNOWN_COMMANDS:
        return command
    if registered and isinstance(command, str):
        label = f"{group}-{command}" if isinstance(group, str) and group else command
        if _LABEL.fullmatch(label):
            return label
    return "other"


def context_map(pool, fn, items):
    """`pool.map` that keeps the caller's declared query identity.

    A ThreadPoolExecutor worker does not inherit the submitting thread's
    contextvars, so reads made there lost their st command label (aegis-z29i).
    Each call runs in its own copy of the caller's context.
    """
    context = contextvars.copy_context()
    return pool.map(lambda item: context.copy().run(fn, item), items)


@contextmanager
def declared_command(command, group=None, *, registered=False):
    """Finite command label only: never argv, subjects, paths, or message text.

    The outer entrypoint owns attribution through nested stop hooks; source is
    diagnostic, not an actor or authority. Context restoration includes errors.
    """
    label = command_label(command, group, registered=registered)
    token = _command.set(_command.get() or "st-" + label)
    try:
        yield
    finally:
        _command.reset(token)
