#!/usr/bin/env python3
"""Exercise the real Seeds adapter against an isolated local fixture."""
from argparse import Namespace
import json
import os
from pathlib import Path
import subprocess
import tempfile

from shantytown.br import UpdateConflict
from shantytown.sd import SdTracker
from shantytown.work_item import command


def main():
    binary = os.environ['ST_DEMO_SD']
    with tempfile.TemporaryDirectory(prefix='work-revision-demo-') as root:
        root = Path(root)
        (root / 'home').mkdir()
        (root / 'work').mkdir()
        base_env = dict(os.environ)
        base_env.pop('PYTHONPATH', None)
        help_result = subprocess.run(['st', 'work', 'item', 'update', '--help'],
            cwd=root / 'work', env=base_env, capture_output=True, text=True, check=False)
        assert help_result.returncode == 0
        print('Installed CLI exposes --if-revision:', '--if-revision' in help_result.stdout, flush=True)
        for key in list(os.environ):
            if key.startswith(('SEEDS_', 'BR_')):
                os.environ.pop(key)
        os.environ.update(HOME=str(root / 'home'), XDG_CONFIG_HOME=str(root / 'home/config'),
                          SHANTY_SD_BIN=binary, SEEDS_PREFIX='demo')
        store = root / 'fixture.db'

        def sd(*args):
            result = subprocess.run([binary, '--store', str(store), *args, '--json'],
                cwd=root / 'work', capture_output=True, text=True, check=False)
            assert result.returncode == 0
            return json.loads(result.stdout)

        made = sd('create', 'Adapter conflict fixture')
        item = made['id']
        tracker = SdTracker(repo=str(root / 'work'), store=str(store), prefix='demo')
        first_read = command(Namespace(item=item, item_action='show'), tracker)
        print('Candidate API exact read revision:', first_read['revision'], flush=True)
        sd('update', item, '--notes', 'author-one', '--if-revision', '1')
        notes = root / 'notes.txt'
        notes.write_text('stale author-two')
        args = Namespace(item=item, item_action='update', dry_run=False,
                         notes_file=notes, replace_text=True, if_revision=1)
        print('$ work_item.command(update, if_revision=1)', flush=True)
        try:
            command(args, tracker)
        except UpdateConflict as conflict:
            print(str(conflict), flush=True)
        else:
            raise AssertionError('stale update must refuse')
        assert tracker.get(item).notes == 'author-one'
        print('First writer preserved; no automatic retry.', flush=True)
        args.if_revision = 2
        notes.write_text('author-one; explicitly rebased author-two')
        print('$ work_item.command(update, if_revision=2)', flush=True)
        result = command(args, tracker)
        print(json.dumps(result, sort_keys=True), flush=True)
        final = tracker.get(item)
        assert final.revision == 3 and final.notes == notes.read_text()
        print('Final revision:', final.revision, flush=True)


if __name__ == '__main__':
    main()
