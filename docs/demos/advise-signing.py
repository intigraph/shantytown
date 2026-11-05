"""Repeatable library demo: real adapter, synthetic identity/command transport."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--label', required=True)
args = parser.parse_args()
sys.path.insert(0, args.source)
from shantytown.sd import SdTracker
try:
    from shantytown import advise_signing
except ImportError:
    advise_signing = None

print(args.label + ': real Seeds adapter, synthetic transport; no network or keys')
with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
    root = Path(directory)
    profile = root / 'profile'
    profile.mkdir(mode=0o700)
    (profile / 'seeds').mkdir(mode=0o700)
    config = profile / 'seeds/config.toml'
    config.write_text('[quipu]\nsigning_key_file="/synthetic/key"\n'
                      'signing_session="demo-session"\nsigning_introducer="lead"\n'
                      'require_identity=false\nactor_principal_mode="observe"\n')
    config.chmod(0o600)
    policy = root / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'mode': 'advise', 'profiles': {
        'worker': {'config_dir': str(profile),
                   'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest()}}}))
    policy.chmod(0o600)
    if advise_signing:
        stack.enter_context(patch.object(advise_signing, 'POLICY_PATH', policy))
        stack.enter_context(patch.object(advise_signing, 'POLICY_OWNER', os.geteuid()))
    stack.enter_context(patch.dict(os.environ, {'SHANTY_AGENT': 'worker'}))
    stack.enter_context(patch('shantytown.actor_identity.authenticated_actor', return_value=None))
    stack.enter_context(patch.object(SdTracker, 'prove_store', return_value=None))
    stack.enter_context(patch('shantytown.sd.sdk_subprocess_options', return_value={'env': {}}))
    def run(command, **options):
        kind = 'identity' if 'identity' in command else 'mutation'
        selected = options['env'].get('XDG_CONFIG_HOME') == str(profile)
        print('  child:', kind, 'credentials:', 'per-agent profile' if selected else 'legacy')
        answer = json.dumps({'authenticated': True, 'auth_class': 'attested_session',
                             'principal': 'worker', 'session': 'demo-session',
                             'key_id': 'sha256:' + 'a' * 64}) if kind == 'identity' else ''
        return subprocess.CompletedProcess(command, 0, answer, '')
    stack.enter_context(patch('shantytown.sd.subprocess.run', side_effect=run))
    tracker = SdTracker(quipu='https://example.invalid', prefix='demo')
    for actor in ('worker', 'different-actor'):
        print('asserted actor:', actor)
        result = tracker._bd_in(None, '--actor=' + actor, 'comments', 'add', 'demo', '--text', 'fixture')
        print('  command exit:', result.returncode)
        log = profile / 'writes.jsonl'
        if log.exists():
            event = json.loads(log.read_text().splitlines()[-1])
            print('  observed:', {k: event[k] for k in ('actor', 'principal', 'match', 'command_exit')})
        else:
            print('  observed: no per-write key/principal receipt')
