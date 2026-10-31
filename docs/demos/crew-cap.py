import subprocess, types
from shantytown.answer import Answer
import shantytown.plate_capacity as candidate
base = types.ModuleType("shantytown._base_demo")
base.__package__ = "shantytown"
exec(subprocess.check_output(["git", "show", "7510e04d:shantytown/plate_capacity.py"]), base.__dict__)
class Rows:
    def __init__(self, count): self.count = count
    def capacity_rows(self, owner):
        return Answer.complete_read([dict(id=f"work-{i}", title="Work", assignee=owner, status="open") for i in range(self.count)], how="isolated complete fixture")
print("Synthetic fixture: complete owner plate; same P0 request on base and candidate.")
for name, module in [("BASE 7510e04d", base), ("CANDIDATE hard-ten", candidate)]:
    for count in [9, 10]:
        try:
            module.ensure_room(Rows(count), "worker", candidate=dict(title="Urgent repair", priority=0))
            outcome = "ADMITTED"
        except module.PlateFull:
            outcome = "REFUSED"
        print(f"{name}: held={count}/10 new=P0 -> {outcome}")
        assert outcome == ("REFUSED" if name.startswith("CANDIDATE") and count == 10 else "ADMITTED")
print("No backend write, dispatch, or installed-behavior claim.")
