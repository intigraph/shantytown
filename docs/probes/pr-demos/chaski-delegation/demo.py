"""Offline local evaluator fixture; no tracker, pane, scheduler or network."""
import ast
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from shantytown import cli, config, jobs

BASE = "7923c5cfc68057406a39c4aee6479f6e509954bf"


def exercise(label, scheduler, base=False):
    attempts = []
    with tempfile.TemporaryDirectory(prefix="scheduler-demo-") as directory:
        root = Path(directory)
        (root / config.CONFIG_NAME).write_text(f'[jobs]\nscheduler = "{scheduler}"\n')
        (root / "jobs").mkdir()
        (root / "jobs" / "fixture.toml").write_text(
            '[trigger]\nevery = "1h"\n[action]\ninbox = "fixture"\nmessage = "offline"\n')

        def deliver(job, fire, rendered):
            attempts.append(job.name)
            return jobs.Outcome(True, "offline delivery witness")

        def runner(_):
            return jobs.Runner(root, host="fixture", now=lambda: 1_000_000,
                               actions={"inbox": deliver}, detach=False)

        if base:
            source = subprocess.check_output(
                ["git", "show", f"{BASE}:shantytown/cli.py"], text=True)
            function = next(n for n in ast.parse(source).body
                            if isinstance(n, ast.FunctionDef) and n.name == "_jobs_sweep")
            namespace = {"_jobs_runner": runner}
            exec(compile(ast.Module(body=[function], type_ignores=[]), "<base evaluator>", "exec"), namespace)
            namespace["_jobs_sweep"](SimpleNamespace(root=root))
        else:
            original = cli._jobs_runner
            try:
                cli._jobs_runner = runner
                cli._jobs_sweep(SimpleNamespace(root=root))
            finally:
                cli._jobs_runner = original
        print(f"{label}: local delivery attempts = {len(attempts)}")
        return len(attempts)


if __name__ == "__main__":
    assert exercise("BASE / Chaski declaration", "chaski", base=True) == 1
    assert exercise("CANDIDATE / Chaski delegation", "chaski") == 0
    assert exercise("CONTROL / local scheduler", "local") == 1
