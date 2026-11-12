"""Offline ownership probe on base and candidate; no tracker or process calls."""
import subprocess
from shantytown.stranded_work import eligible

BASE = "6bccc8d7f1f502e12daba586d8fb6e47002924b4"
source = subprocess.check_output(["git", "show", BASE + ":shantytown/stranded_work.py"], text=True)
namespace = {"__package__": "shantytown"}
exec(compile(source, "base/stranded_work.py", "exec"), namespace)
print("Synthetic fixture: operator-stopped owner; assigned open P0 work")
print("Base:", BASE)
for name, predicate in [("before", namespace["eligible"]), ("after", eligible)]:
    print(name)
    for label in [[], ["deploy-operation"]]:
        row = dict(id="fixture-op", title="work", assignee="worker", status="open",
                   priority=0, labels=label, revision=1)
        result = predicate(row, operator_stopped=True)
        print("  " + ("deploy reservation" if label else "ordinary work") + ": release eligible=" + str(result))
        assert result == (name == "before" or not label)
