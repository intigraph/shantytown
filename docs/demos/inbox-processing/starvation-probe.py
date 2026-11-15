"""Private files fixture for ordinary CLI selection; never reads a live inbox."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from shantytown import cli
from shantytown.inbox import FilesInbox
from shantytown.inbox_disposition import ControlledInbox, Dispositions

with TemporaryDirectory() as directory:
    root = Path(directory)
    raw = FilesInbox(root / 'inbox')
    state = Dispositions(root, 'files')
    duplicates = [raw.deliver('reader', 'Synthetic unchanged finding', 'producer') for _ in range(34)]
    state.set(duplicates[0], 'ack', 'tracked in this private fixture')
    changed = raw.deliver('reader', 'Synthetic NEW critical finding', 'producer')
    command = argparse.Namespace(count=False, read=True, read_id=[], dry_run=False)
    with patch.object(cli, '_inbox', return_value=ControlledInbox(raw, state)):
        print('ordinary st inbox --read, after 34 retained processing-ACK repeats:')
        result = cli._inbox_read(command, 'reader')
    print('CLI exit:', result)
    print('changed finding acknowledged:', raw.get_message('reader', changed.id).read)
    print('suppressed original records retained:', sum(raw.get_message('reader', m.id) == m for m in duplicates))
