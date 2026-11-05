#!/usr/bin/env python3
"""Policy-to-job-config demo; native ownership and sd response are mocked."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from shantytown import actor_identity, job_launch

BASE = '9697c751'


def run(module, policy, directory):
    called = []
    def sd(argv, **options):
        called.append(argv)
        selected = options['env'].get('XDG_CONFIG_HOME')
        print('sd identity config:', 'operator fixture' if selected == str(directory) else 'unselected')
        assert selected == str(directory)
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(
            authenticated=True, auth_class='attested_session', principal='synthetic-owner',
            key_id='sha256:' + 'a' * 64, session='synthetic-session')))
    try:
        principal = module.authenticated_actor(policy_path=policy, run=sd)
        print('authenticated principal:', principal)
        return principal, called
    except actor_identity.IdentityError as error:
        print('refused:', str(error))
        return None, called
    except RuntimeError as error:
        # The baseline defines its own IdentityError class.
        print('refused:', str(error))
        return None, called


def main():
    old = ModuleType('baseline_actor_identity')
    old.__package__ = 'shantytown'
    source = subprocess.check_output(['git', 'show', BASE + ':shantytown/actor_identity.py'], text=True)
    exec(compile(source, 'baseline_actor_identity.py', 'exec'), old.__dict__)
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary)
        directory = home / 'operator-config'
        (directory / 'seeds').mkdir(parents=True)
        ca = directory / 'ca.pem'
        ca.write_bytes(b'synthetic public CA bytes')
        ca.chmod(0o644)
        config = directory / 'seeds/config.toml'
        config.write_text('[quipu]\nca_file = ' + json.dumps(str(ca)) + '\nca_sha256 = "' +
                          hashlib.sha256(ca.read_bytes()).hexdigest() + '"\n')
        config.chmod(0o644)
        policy = home / 'identity.json'
        policy.write_text(json.dumps(dict(version=1, required=True, users={'51001':dict(
            principal='synthetic-owner', home=str(home), endpoint='https://graph.example.invalid',
            sd='/usr/bin/sd', seeds_config_dir=str(directory))})))
        policy.chmod(0o644)
        owner = os.geteuid()
        def protected(path, **kwargs):
            path = Path(path)
            if path.is_symlink() or not path.exists():
                raise actor_identity.IdentityError('invalid fixture path')
        with patch.object(os, 'geteuid', return_value=51001), \
             patch.object(actor_identity, 'TRUSTED_POLICY_OWNER', owner), \
             patch.object(old, 'TRUSTED_POLICY_OWNER', owner), \
             patch.object(job_launch, 'protected', protected), \
             patch.dict(os.environ, {'XDG_CONFIG_HOME':'/untrusted/controller-config'}, clear=True):
            print('Fixture: protected ownership/UID and sd response mocked; actual config files and SHA-256.')
            print('before source', BASE)
            result, called = run(old, policy, directory)
            assert result is None and not called
            print('after source: current checkout')
            result, called = run(actor_identity, policy, directory)
            assert result == 'synthetic-owner' and len(called) == 1
            ca.write_bytes(b'changed CA bytes')
            print('after / changed CA bytes')
            result, called = run(actor_identity, policy, directory)
            assert result is None and not called
            print('Config propagation and pre-sd tamper refusal demonstrated. No native identity acceptance.')


if __name__ == '__main__':
    main()
