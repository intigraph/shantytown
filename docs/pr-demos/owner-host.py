"""Replay owner placement proof locally; no tracker/model/pane mutations.

python3 owner-host.py --source /path/to/source-checkout
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);args=ap.parse_args()
sys.path.insert(0,str(Path(args.source).resolve()))
from shantytown import board_rank as rank
from shantytown.answer import Answer
from shantytown.protocols import Agent

for placement in (None,'','here','other'):
    probes=[]
    card=Agent('worker',host=placement,pane='worker-pane')
    registry=NS(all=lambda:Answer.complete_read([card],how='isolated fixture'))
    states=rank.owner_states(registry,NS(exists=lambda pane:probes.append(pane) or False),host='here',peers=[])
    row=dict(id='task',title='work',description='',status='open',assignee='worker',priority=1,
             labels=[],blocked_by=[],created_at='2026-10-01T00:00:00Z')
    result=rank.propose([row],{kind:{'iri':'urn:rule:'+kind} for kind in rank.KINDS},states,
                        now=datetime(2026,11,4,tzinfo=timezone.utc))
    proposal=result['proposals'][0]
    print(json.dumps(dict(card_host=placement,owner_state=proposal['owner_state'],
        reowner_proposal=proposal['reowner'],local_pane_probes=probes,
        changes_applied=result['changes_applied'])))
