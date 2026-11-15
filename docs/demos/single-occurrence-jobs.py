"""Pure typed-reader before/after demo. Optional --before points to a base source file."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from shantytown import quipu_jobs as current
from test_quipu_jobs import one_shot_catalogue

args=argparse.ArgumentParser();args.add_argument('--before',type=Path);args=args.parse_args()
if args.before:
    spec=importlib.util.spec_from_file_location('shantytown.quipu_jobs_before',args.before)
    before=importlib.util.module_from_spec(spec);sys.modules[spec.name]=before;spec.loader.exec_module(before)
    try:before.decode_catalogue(one_shot_catalogue())
    except before.JobRefused as exc:print('BASE: REFUSED',str(exc))
    else:raise AssertionError('base unexpectedly accepted the single occurrence')
job,=current.decode_catalogue(one_shot_catalogue())
print('CANDIDATE:',json.dumps(dict(repeat_count=job.repeat_count,interval_s=job.interval_s,anchor_s=job.anchor_s)))
body=one_shot_catalogue()
next(r for r in body['rows'] if r['p']==current.SCHEMA+'repeatCount')['o']=2
try:current.decode_catalogue(body)
except current.JobRefused as exc:print('COUNT=2 CONTROL: REFUSED',str(exc))
else:raise AssertionError('unsupported recurrence accepted')
print('Pure fixture only; no graph, scheduler, key or runtime reads.')
