"""Same mocked Seeds rows through the real SdTracker plate on base and candidate source."""
import os
from pathlib import Path
import subprocess
import sys

PROBE = '''
import json, subprocess
from shantytown import br
from shantytown.sd import SdTracker, StoreProof
SdTracker.prove_store = lambda self: StoreProof("--quipu", None, "https://example.test", "test")
SdTracker._use_remote_projection = lambda self: False
br.name_the_blocker = lambda _, item: item
def row(i, p, lane=None, rank=None, created="2026-11-01T00:00:00Z"):
    return dict(id=i, title=i, assignee="worker", status="open", priority=p,
                lane=lane, rank=rank, created_at=created)
rows = [row("p0-unlaned", 0, created="2026-10-01T00:00:00Z"),
        row("p3-next-rank2", 3, "next", "2"), row("p4-next-rank1", 4, "next", "1")]
t = SdTracker(quipu="https://example.test", prefix="test")
def run(*args):
    status = args[args.index("--status") + 1] if "--status" in args else None
    sel = [x for x in rows if status is None or x["status"] == status]
    return subprocess.CompletedProcess(args, 0, json.dumps({"issues": sel, "total": len(sel), "has_more": False}), "")
t._bd = run
print("lanes next(2), no now      -> plate:", br.plate(t, "worker").id)
rows.append(row("p4-now", 4, "now"))
print("add one Now item           -> plate:", br.plate(t, "worker").id)
for x in rows: x["lane"] = None; x["rank"] = None
print("control, no lanes anywhere -> plate:", br.plate(t, "worker").id)
'''
for label, source in [("base", os.environ["LANE_BASE_SOURCE"]), ("head", os.environ["LANE_HEAD_SOURCE"])]:
    source = Path(source)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    print(label, "source", revision, flush=True)
    print("$ same mocked Seeds rows -> br.plate(worker)", flush=True)
    env = {**os.environ, "PYTHONPATH": str(source)}
    subprocess.run([sys.executable, "-c", PROBE], env=env, cwd=source, check=True)
