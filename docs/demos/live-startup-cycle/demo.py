"""Library fixture: no process, pane, tracker or provider is changed."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import cli, cycle, provision
from shantytown.protocols import Agent

BASE = "c96be285f052ae5ec709137842240bea0b887ce1"
before = ModuleType("shantytown._u930_before")
before.__package__ = "shantytown"
sys.modules[before.__name__] = before
exec(compile(subprocess.check_output(
    ["git", "show", BASE + ":shantytown/cli.py"], cwd=ROOT),
    "before_cli.py", "exec"), before.__dict__)


def observe(module, live):
    effects = []
    with ExitStack() as stack:
        stack.enter_context(patch.object(provision, "preflight_credentials", lambda *a: None))
        for name, value in {
            "_foreign_session_refusal": lambda *a: None,
            "_capture_history_before_kill": lambda *a: None,
            "_launch": lambda *a, **kw: effects.append("respawn") or module.CANNOT_TELL,
            "_launch_admitted": lambda *a, **kw: effects.append("second-restart-admission") or module.REFUSED,
        }.items():
            stack.enter_context(patch.object(module, name, value))
        panes = SimpleNamespace(capture=lambda *a: "fixture", exists=lambda *a: True)
        runtime = SimpleNamespace(is_live=lambda screen: live)
        result = module._restart_cycle(SimpleNamespace(), Agent("worker", harness="claude"),
            "worker", "fixture", panes, runtime, cycle.Plan(cycle.RESPAWN, "fixture"), None)
    return result, effects


print("Source fixture only: unverified startup; no actual restart or elapsed-time claim.")
print("Base:", BASE)
old = observe(before, True)
new = observe(cli, True)
dead = observe(cli, False)
print("Before LIVE:", old)
print("After LIVE:", new)
print("After NOT LIVE control:", dead)
assert old[1] == ["respawn", "second-restart-admission"]
assert new == ((cli.CANNOT_TELL, cycle.RESPAWN), ["respawn"])
assert dead[1] == old[1]
