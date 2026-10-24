"""Private real-file inbox demo; synthetic clock and pane, no service or runtime."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from shantytown import admin_inbox
from shantytown.inbox import FilesInbox

with TemporaryDirectory(prefix='routine-inbox-demo-') as scratch:
    root = Path(scratch)
    box = FilesInbox(root / 'inbox')
    card = SimpleNamespace(name='fixture-admin', pane='fixture-pane', retired=False)
    submitted = []
    panes = SimpleNamespace(exists=lambda _: True,
                            send=lambda pane, text: submitted.append(text),
                            capture=lambda *a, **kw: '')
    with patch.object(admin_inbox, 'wait_for', return_value=900):
        for message in ('[from fixture-worker] routine one', '[from fixture-worker] routine two'):
            admin_inbox.enqueue(root, card, box.deliver(card.name, message),
                                'files', 900, now=1000)
        print('Persisted before live send:', len(box.unread(card.name)), 'unread pointers')
        admin_inbox.sweep(root, [card], panes, lambda _: box, now=1899)
        print('Before deadline:', len(submitted), 'submissions;', len(box.unread(card.name)), 'unread')
        admin_inbox.sweep(root, [card], panes, lambda _: box, now=1900)
        print('At deadline:', len(submitted), 'batch;', len(box.unread(card.name)), 'unread')
        print('Verified sender text retained:', submitted[0].splitlines()[0])
        admin_inbox.sweep(root, [card], panes, lambda _: box, now=2000)
        print('After second sweep:', len(submitted), 'total submissions')
        assert len(submitted) == 1 and box.unread(card.name) == []
