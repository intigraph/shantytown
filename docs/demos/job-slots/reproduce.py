"""Private fixture demo: no sudo, accounts, launch, or live inventory access.

Run from a source checkout with its development pytest dependency installed:
python -B docs/demos/job-slots/reproduce.py
"""
import sys,tempfile,os
from pathlib import Path
import pytest
root = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'tests'))
import test_job_launch as fixture
from shantytown import job_launch as jobs
from shantytown.ephemeral import Request
from shantytown.actor_identity import IdentityError
os.umask(0o077)
with tempfile.TemporaryDirectory() as directory:
 mp=pytest.MonkeyPatch()
 try:
  capability=fixture.capability.__wrapped__(Path(directory),mp)
  original,raw,plan,bindings,file,output,render=fixture.render_fixture(capability,64)
  print('MIXED INVENTORY:',len(jobs.inventory()),'valid identities')
  chosen,_=jobs.select(Request('task','item-1',harness='codex'),root=original['controller_root'],harness='codex',used=set(),native_probe=False)
  print('EXISTING SLOT:',chosen['uid'],'selectable')
  try:jobs.select(Request('task','new-0',harness='codex'),root=original['controller_root'],harness='codex',used=set(),native_probe=False)
  except IdentityError as error:print('UNBOUND SLOT:',str(error))
  result=render();print('RENDERED:',result['bound'],'independent bindings;',result['slots'],'total slots')
  mp.setattr(jobs,'BASE',output)
  for index in (0,63):
   chosen,_=jobs.select(Request('task','new-'+str(index),harness='codex'),root=original['controller_root'],harness='codex',used=set(),native_probe=False)
   print('BOUND REQUEST:',index,'selects UID',chosen['uid'])
  print('EXISTING MANIFEST BYTE-IDENTICAL:',(output/(original['principal']+'.json')).read_bytes()==raw)
 finally:mp.undo()
