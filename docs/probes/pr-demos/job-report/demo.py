import subprocess
import tempfile
from pathlib import Path
from shantytown import ephemeral as eph
old = subprocess.check_output(["git", "show", "a21237ab:shantytown/ephemeral.py"], text=True)
ns = dict(eph.__dict__)
exec(compile(old, "baseline", "exec"), ns)
for job in ("triage", "task"):
    rec = dict(job=job, harness="codex", name=f"eph-{job}-demo")
    print(f"{job}: before rules={ns['codex_job_rules'](rec, unattended=False)!r}")
    with tempfile.TemporaryDirectory() as directory:
        path = eph.write_codex_job_rules(rec, Path(directory), unattended=False)
        for command in (["st", "agent", "spawn", "--report", "--verdict", "blocked", "--summary-file", "-"], ["st", "agent", "spawn", "--merge"], ["git", "push"]):
            result = subprocess.check_output(["codex", "execpolicy", "check", "-r", str(path), *command], text=True)
            print("after", " ".join(command), result.strip())
