"""Compare the real startup function before/after in private temporary fixtures."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parents[3]
base = "dbdce031b1f4f776251122eb69d265ecadc23bc2"
demo = Path(__file__).with_name("reproduce.py")
with TemporaryDirectory(prefix="startup-marker-base-") as temp:
    archive = subprocess.check_output(["git", "archive", base], cwd=root)
    subprocess.run(["tar", "-x", "-C", temp], input=archive, check=True)
    for label, source in (("Before", Path(temp)), ("After", root)):
        print(label, flush=True)
        subprocess.run([sys.executable, str(demo), str(source)], check=True)
