"""Offline receiver comparison; synthetic enrollment and launcher, real sockets/state."""
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

BASE = 'e7f9b54064d4abcc5eb51bdc00f853d0a7311ee5'


def probe(source):
    sys.path[:0] = [str(source), str(source / 'tests')]
    try:
        from shantytown import recruit_receiver as receiver
    except ImportError:
        print('protected inherited receiver: unavailable on base')
        return
    import pytest
    from shantytown.actor_identity import IdentityError
    from test_recruit_store import private_store
    from test_recruit_handoff import ctx
    from test_recruit_launch import native, states
    from test_recruit_receiver import listening, request
    print('SYNTHETIC protected enrollment and launcher; REAL Unix socket/signature/SQLite/native spawn ledger')
    with tempfile.TemporaryDirectory(prefix='receiver-demo-', dir='/tmp') as temp:
        with pytest.MonkeyPatch.context() as patch:
            context = ctx.__wrapped__(private_store.__wrapped__(Path(temp), patch), patch)
            sample = native.__wrapped__(context, patch)
            enabled = sample.kwargs['policy']
            sample.kwargs['policy'] = replace(enabled, recruitment_launch_ready=False)
            try:
                receiver.launch_once(None, args=sample.args, **sample.kwargs)
            except IdentityError:
                print('default activation gate: REFUSED; accepted connections=0; launcher calls=0')
            else:
                raise AssertionError('disabled gate admitted')
            sample.kwargs['policy'] = enabled
            fixture = listening.__wrapped__(sample, patch)
            listener, descriptor = next(fixture)
            try:
                answer = request(sample, listener)
                assert answer['state'] == 'launched' and len(sample.launched) == 1
                print(json.dumps({'state': answer['state'], 'fixture_launcher_calls': len(sample.launched),
                                  'durable_states': states(sample), 'listener_retained': listener.fileno() >= 0}))
                try:
                    request(sample, listener)
                except IdentityError:
                    print('same signed request replay: REFUSED; fixture launcher calls=1')
                else:
                    raise AssertionError('replay launched twice')
                descriptor['controller_uid'] += 1
                try:
                    receiver.launch_once(listener, args=sample.args, timeout=.01, **sample.kwargs)
                except IdentityError:
                    print('wrong configured controller UID: REFUSED before accept; fixture launcher calls=1')
                else:
                    raise AssertionError('wrong controller admitted')
            finally:
                fixture.close()
    print('No live enrollment, socket installation, service or actual job launch.')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--probe':
        probe(Path(sys.argv[2]))
    else:
        root = Path(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == '--source' else Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix='receiver-base-') as temp:
            raw = subprocess.check_output(['git', '-C', str(root), 'archive', BASE, 'shantytown'])
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                archive.extractall(temp, filter='data')
            print('BEFORE source ' + BASE, flush=True)
            subprocess.run([sys.executable, __file__, '--probe', temp], check=True)
            print('AFTER candidate worktree (commit identity is supplied in caption)', flush=True)
            subprocess.run([sys.executable, __file__, '--probe', str(root)], check=True)
