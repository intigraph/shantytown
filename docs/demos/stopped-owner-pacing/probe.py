"""Actual alerter, 85 private fixture rows; no real board or pane delivery."""
import hashlib
from pathlib import Path
import sys
import tempfile
from dataclasses import replace

source = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(source), str(source / 'tests')]
import pytest
from shantytown import deferrals
from shantytown.stopped import FilesStops
from test_deferral_owner_routing import NOW, harness

with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
    root = Path(directory)
    h = harness(root, patch)
    rows = [{**h.row, 'id': f'test-wait-{n}', 'priority': n % 4} for n in range(85)]
    findings = [replace(h.finding, bead=row['id'], priority=row['priority']) for row in rows]
    h.alerter._read = lambda: rows
    h.alerter._show = {row['id']: row for row in rows}.__getitem__
    patch.setattr(deferrals, 'evaluate', lambda *a, **kw: findings)
    FilesStops(root / 'stopped').record('worker', NOW.timestamp())
    h.alerter.sweep()
    print('source_sha256=' + hashlib.sha256(b''.join(
        (source / 'shantytown' / name).read_bytes()
        for name in ('notify.py', 'deferral_pacing.py', 'deferral_stopped.py')
        if (source / 'shantytown' / name).is_file())).hexdigest())
    print(f"lead_wakes={sum(pane == 'lead' for pane, _ in h.sent)} admin_digests={len(h.admins)}")
    print(f"held_rows={sum(row['status'] == 'deferred' for row in rows)}/{len(rows)}")
    h.alerter.sweep()
    print(f"after_repeat: lead_wakes={sum(pane == 'lead' for pane, _ in h.sent)} admin_digests={len(h.admins)}")
    for text in h.admins:
        print(text)
