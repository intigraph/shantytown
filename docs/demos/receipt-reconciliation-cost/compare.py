"""Compare one frozen stopped-owner tick on exact archived base and candidate."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = '6c52e0ba54cca8beb1b9a6a697686f06da4fd6e8'
TEST = 'tests/test_owned_receipt_cost.py'
CASE = 'test_known_delivery_does_not_select_retained_history'
print('Frozen input: 100 closed receipts + one stopped worker delivery', flush=True)
print('Base:', BASE, flush=True)
print('Candidate:', subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), flush=True)
with tempfile.TemporaryDirectory(prefix='st-receipt-base-') as scratch:
    base = Path(scratch)
    data = subprocess.check_output(['git','archive','--format=tar',BASE],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(base, filter='data')
    (base/TEST).write_bytes((ROOT/TEST).read_bytes())
    for label,root in [('BEFORE',base),('AFTER',ROOT)]:
        print('\n'+label+': same real stopped-owner tick, serialized HTTP fixture',flush=True)
        env=os.environ.copy();env['PYTHONPATH']=str(root)
        result=subprocess.run(['python3','-m','pytest','-q','--tb=short','--disable-warnings',TEST+'::'+CASE],cwd=root,env=env)
        print(label,'exit',result.returncode,flush=True)
        if (label=='BEFORE' and result.returncode!=1) or (label=='AFTER' and result.returncode!=0):
            raise SystemExit('Unexpected comparison outcome')
print('Observed: baseline selected 101 receipt subjects; candidate selects one.',flush=True)
print('This is frozen source behavior, not production recovery or runtime activation.',flush=True)
