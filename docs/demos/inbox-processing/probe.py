"""Synthetic local files only; no crew registry, network, live inbox or clock change."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from shantytown.inbox import FilesInbox

mode = sys.argv[1]
with TemporaryDirectory() as directory:
    root = Path(directory)
    raw = FilesInbox(root / 'inbox')
    original = raw.deliver('reader', 'Synthetic unchanged CVE digest', 'producer')
    raw.mark_read('reader', [original.id])
    if mode == 'candidate':
        from shantytown.inbox_disposition import ControlledInbox, Dispositions
        store = Dispositions(root, 'files')
        store.set(original, 'ack', 'already tracked')
        box = ControlledInbox(raw, store)
    else:
        box = raw
    for _ in range(34):
        raw.deliver('reader', original.body, original.frm)
    print(f'{mode}: 34 identical repeats after receipt ACK -> {len(box.unread("reader"))} eligible')
    print(f'{mode}: retained duplicate evidence -> {len(raw.unread("reader"))} stored unread')
    if mode == 'candidate':
        changed = raw.deliver('reader', 'Synthetic NEW critical finding', 'producer')
        assert box.unread('reader') == [changed]
        print('changed finding -> eligible immediately')
        store.set(original, 'defer', 'await next window', now=100, until=200)
        print('defer before deadline ->', store.visible(original, now=199))
        print('defer at deadline, original ->', store.visible(original, now=200))
        assert store.visible(original, now=200)
        assert not store.visible(raw.unread('reader')[0], now=200)
        print('defer at deadline, duplicate -> False (original only)')
