#!/usr/bin/env python3
"""Compare startup text using inert plate and memory readers, without launching agents."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', type=Path, required=True)
args = parser.parse_args()
code = '''from shantytown import session_anchor as s, crew_memory, prime
s._run_anchor = lambda *a: (0, "  You are example — worker.\\n  Current work: example-1")
crew_memory.for_agent = lambda *a: ""
text = s.render("/inert-fixture", "example")
print("normal startup directive instruction:", "record new operator directives" in text)
s._run_anchor = lambda *a: (2, "")
prime.primer = lambda: "## Other\\nmissing orientation\\n"
text = s.render("/inert-fixture", "example")
print("unreadable plate and primer directive instruction:", "record new operator directives" in text)
'''
for label, root in [('BEFORE', args.baseline), ('AFTER', Path.cwd())]:
    print(label, flush=True)
    subprocess.run([sys.executable, '-c', code], cwd=root, check=True,
                   env={**os.environ, 'PYTHONPATH': str(root.resolve()),
                        'PYTHONDONTWRITEBYTECODE': '1'})
