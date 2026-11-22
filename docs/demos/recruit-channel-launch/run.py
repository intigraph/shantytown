"""Offline library comparison; no pane, privileged helper or service starts."""
from pathlib import Path
import io
import json
import subprocess
import sys
import tarfile
import tempfile


def probe(source):
    sys.path[:0] = [str(source), str(source / 'tests')]
    try:
        from shantytown import recruit_channel as bridge
        if not hasattr(bridge, "launch_connected"):
            raise ImportError
    except ImportError:
        print('connected controller launch: unavailable on base')
        return
    from dataclasses import replace
    import pytest
    from test_recruit_store import private_store
    from test_recruit_handoff import ctx
    from test_recruit_launch import native, states
    from test_recruit_channel_launch import exchange
    from shantytown.actor_identity import IdentityError
    print('SYNTHETIC enrollment, forge and launcher; real signature/store/planner/ledger/card')
    with tempfile.TemporaryDirectory(prefix='recruit-channel-launch-demo-') as temp:
        with pytest.MonkeyPatch.context() as patch:
            fixture = private_store.__wrapped__(Path(temp), patch)
            context = ctx.__wrapped__(fixture, patch)
            sample = native.__wrapped__(context, patch)
            enabled = sample.kwargs['policy']
            sample.kwargs['policy'] = replace(enabled, recruitment_launch_ready=False)
            try:
                bridge.launch_connected(None, args=sample.args, **sample.kwargs)
            except IdentityError:
                print('default activation gate: REFUSED; launcher calls=0')
            else:
                raise AssertionError('disabled gate admitted launch')
            sample.kwargs['policy'] = enabled
            answer, observed = exchange(sample, patch)
            assert observed == [answer]
            assert answer['state'] == 'launched' and len(sample.launched) == 1
            print(json.dumps({'state': answer['state'], 'head': answer['head'],
                              'fixture_launcher_calls': len(sample.launched),
                              'durable_states': states(sample)}))
            try:
                exchange(sample, patch)
            except IdentityError:
                print('reopen and replay: REFUSED; fixture launcher calls=1')
            else:
                raise AssertionError('replay admitted launch')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--probe':
        probe(Path(sys.argv[2]))
    else:
        root = Path(__file__).resolve().parents[3]
        base = '7a2df4c89fbbae1a2809e5a591157afa9c1d6486'
        head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        with tempfile.TemporaryDirectory(prefix='recruit-channel-launch-base-') as temp:
            data = subprocess.check_output(['git', '-C', str(root), 'archive', base, 'shantytown'])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                archive.extractall(temp, filter='data')
            print('BEFORE source ' + base, flush=True)
            subprocess.run([sys.executable, __file__, '--probe', temp], check=True)
            print('AFTER candidate source ' + head, flush=True)
            subprocess.run([sys.executable, __file__, '--probe', str(root)], check=True)
