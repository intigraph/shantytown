"""Offline wire fixture; no SSH, service calls, registry or real cache."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shantytown import crew_display as display, fleet
from shantytown.config import HostPeer

base = 'f909de3e3ba445946545dd673f94edea1de2d0fd'
probe = subprocess.run(['git', 'cat-file', '-e', base + ':shantytown/crew_display.py'], capture_output=True)
assert probe.returncode != 0
print('base f909de3e: display protocol module absent')
wire = dict(version=2, purpose='display', decision_eligible=False, scope='local',
            host='fixture', complete=True, agents=[], ttl_seconds=15, age_seconds=0)
peer = HostPeer('fixture', 'fixture.invalid', '/fixture')
def response(*_args, **_kwargs):
    return SimpleNamespace(returncode=0, stdout=json.dumps(wire), stderr='')
with patch.object(display.subprocess, 'run', response):
    assert fleet.read_peer(peer).get('error')
    print('live v1 reader: refuses display v2')
    assert display.read_peer(peer)['complete']
    print('display reader: accepts fresh v2; decision_eligible=false')
    wire['age_seconds'] = 16
    assert not display.read_peer(peer)['complete']
    print('display reader: refuses expired 16s observation')
    wire['age_seconds'] = 0
    wire['decision_eligible'] = True
    assert not display.read_peer(peer)['complete']
    print('display reader: refuses decision-eligible envelope')
print('fixture complete; zero network calls')
