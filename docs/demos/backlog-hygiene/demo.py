"""Same isolated ranking report on base and candidate; no live tracker or sends."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROBE = r'''
import json
from copy import deepcopy
from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import tempfile
from shantytown.answer import Answer
from shantytown.ranking_check import sweep
def row(ident, **extra):
    return dict(id=ident, title=ident, status="open", priority=3, labels=[],
                assignee=None, updated_at="2020-01-01T00:00:00Z") | extra
rows = [row("stale-work"), row("ASK Stiwi retain decision"),
        row("native-operation", agent_context='{"phase":"planned"}')]
before = deepcopy(rows)
reg = SimpleNamespace(all=lambda: Answer.complete_read([], how="isolated fixture"))
panes = SimpleNamespace(exists=lambda p: True)
logs, sent = [], []
side_output = io.StringIO()
with tempfile.TemporaryDirectory() as root, redirect_stdout(side_output):
    result = sweep(
        root, reg, panes, snapshot=lambda: (rows, rows), log=logs.append,
        counts_reader=lambda root: "cohort counts: fixture",
        push=lambda *args: sent.append(args) or True)
assert rows == before and not result and not sent
print(json.dumps(dict(text="\n".join(logs), actionable=bool(sent),
                     advisory_stdout=side_output.getvalue())))
'''


def probe(source):
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory() as folder:
        return json.loads(subprocess.check_output(
            [sys.executable, "-c", PROBE], cwd=folder, env=env, text=True))


def main():
    base = Path(os.environ["HYGIENE_DEMO_BEFORE"])
    current = Path(__file__).resolve().parents[3]
    old, new = probe(base), probe(current)
    print("Target: source library, isolated READY fixture; no live board, claims or sends.")
    print("Input: stale unowned P3, protected ASK, protected native operation.")
    print("Before:")
    print(old["advisory_stdout"], end="")
    print(old["text"])
    print("After:")
    print(new["advisory_stdout"], end="")
    print(new["text"])
    assert "stale-work review" not in old["text"]
    review = new["text"].splitlines()[-1]
    assert "1 unowned P3/P4" in review and "stale-work" in review
    assert "ASK Stiwi" not in review and "native-operation" not in review
    assert not old["actionable"] and not new["actionable"]
    print("Control: ASK and native operation excluded from review; no administrator page.")
    print("Both input snapshots unchanged; closure still requires an independent current read.")


if __name__ == "__main__":
    main()
