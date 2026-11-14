"""Compare stop decisions in private fixtures; never launch an agent."""
import ast
import json
from pathlib import Path
import subprocess
import tempfile

from shantytown import stop_policy


BASE = "2ff8a6115a9c61f33b404a14d258fe962b2c28ee"
root = Path(__file__).resolve().parents[4]
before = subprocess.check_output(
    ["git", "show", f"{BASE}:shantytown/stop_policy.py"], cwd=root, text=True)
after = (root / "shantytown/stop_policy.py").read_text()


def probe(source, ready):
    tree = ast.parse(source)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "ephemeral_free_slots")
    namespace = dict(vars(stop_policy))
    exec(compile(ast.Module(body=[function], type_ignores=[]), "probe", "exec"), namespace)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / "shantytown.toml").write_text(
            "[ephemeral]\nmax_agents = 2\nunattended = true\n"
            f"unattended_uid_ready = {str(ready).lower()}\n")
        (path / "crew").mkdir()
        (path / "crew/boss.json").write_text(json.dumps({
            "role": "administrator", "dangerous": True,
        }))
        slots = namespace["ephemeral_free_slots"](path)
        verdict = stop_policy.decide(stop_policy.Inputs(
            me="boss", role="administrator",
            p0_plate=[stop_policy.P0Item("work", owner="")],
            capacity=stop_policy.Capacity(ephemeral_slots=slots),
        ))
        return f"slots={slots} block={verdict.block} reason={verdict.by}"


print(f"Baseline {BASE}; candidate working source; isolated fixtures, no launches")
for ready in (False, True):
    print(f"unattended=true, uid_ready={ready}")
    print("  before:", probe(before, ready))
    print("  after: ", probe(after, ready))
