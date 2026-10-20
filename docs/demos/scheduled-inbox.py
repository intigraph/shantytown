"""Real child + local inbox fixture; no graph, keys, tmux send or scheduler."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from shantytown.inbox import FilesInbox


def main():
    with tempfile.TemporaryDirectory(prefix='scheduled-inbox-demo-') as temp:
        root = Path(temp)
        (root / 'crew').mkdir()
        (root / 'home').mkdir()
        (root / 'crew' / 'receiver.json').write_text('{"role":"worker"}')
        env = {'HOME': str(root / 'home'), 'PATH': os.defpath,
               'PYTHONPATH': str(SOURCE), 'SHANTY_AGENT': 'scheduler',
               'SHANTY_ENTITY_LINK': 'off'}
        argv = [sys.executable, '-m', 'shantytown.scheduled_inbox',
                '--root', str(root), '--backend', 'files', '--registry', 'files',
                '--sender', 'scheduler', '--recipient', 'receiver',
                '--job', 'synthetic-pilot', '--message', 'synthetic watch request']
        for recipient, expected in [('receiver', 'succeeded'), ('absent', 'failed')]:
            command = argv.copy()
            command[command.index('--recipient')+1] = recipient
            r, w = os.pipe()
            try:
                child = subprocess.run(command, cwd=root,
                    env={**env, 'ST_SCHEDULED_RESULT_FD': str(w)}, pass_fds=(w,),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=20)
                os.close(w)
                w = None
                result = json.loads(os.read(r, 4096))
                assert result == {'schema_version': 1, 'outcome': expected,
                                  'exit_code': child.returncode}
                assert child.returncode == (0 if expected == 'succeeded' else 1)
                print(f'actual child: {expected}; descriptor agrees with exit {child.returncode}')
            finally:
                os.close(r)
                if w is not None:
                    os.close(w)
        message, = FilesInbox(root / 'inbox').unread('receiver')
        assert message.frm == 'scheduler' and '[job synthetic-pilot]' in message.body
        print('actual inbox readback: one attributed pointer; recipient down, not live proof')
        no_channel = subprocess.run(argv, cwd=root, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        assert no_channel.returncode == 2
        assert len(FilesInbox(root / 'inbox').unread('receiver')) == 1
        assert not (root / 'jobs').exists()
        print('missing descriptor: exit 2, no second pointer, no TOML/state created')
        print('SYNTHETIC ONLY: no Chaski slot, signature, production graph or natural firing')


if __name__ == '__main__':
    main()
