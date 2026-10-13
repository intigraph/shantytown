#!/usr/bin/env python3
"""Compare the same private cache-cleanup fixture on baseline and candidate."""
import pathlib,subprocess,tempfile,sys
ROOT=pathlib.Path(__file__).resolve().parents[4]
BASE='4b3ae5ef5f745af7a5c0f72301b2b32f4ad95296'
with tempfile.TemporaryDirectory() as directory:
    baseline=pathlib.Path(directory)
    for name in ['install-scrub-guard.sh','pre-push-scrub-guard.sh','pre-push-gitleaks.sh']:
        p=baseline/name;p.write_bytes(subprocess.check_output(['git','-C',str(ROOT),'show',BASE+':scripts/'+name]));p.chmod(0o755)
    for label,script in [('BEFORE',baseline/'install-scrub-guard.sh'),('AFTER',ROOT/'scripts/install-scrub-guard.sh')]:
        print(label,flush=True)
        subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('probe.py')),str(script)],check=True)
