import subprocess,tempfile
from pathlib import Path
repo=Path(__file__).resolve().parents[3]
probe=repo/"docs/demos/pytest-custody/probe.py"
with tempfile.TemporaryDirectory() as t:
 stage=Path(t)
 for name in ["install-scrub-guard.sh","pre-push-scrub-guard.sh","pre-push-gitleaks.sh"]:
  out=stage/name;out.write_bytes(subprocess.check_output(["git","-C",str(repo),"show","49ce946:"+"scripts/"+name]));out.chmod(0o755)
 print("BASE49ce946: same isolated private pytest fixture + ordinary adjacent repository",flush=True)
 subprocess.run(["python3",str(probe),str(stage/"install-scrub-guard.sh")],check=True)
 print("CANDIDATE: same isolated inputs; ordinary repository must remain armed",flush=True)
 subprocess.run(["python3",str(probe),str(repo/"scripts/install-scrub-guard.sh")],check=True)
