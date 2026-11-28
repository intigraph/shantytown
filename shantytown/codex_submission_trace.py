"""Bounded private launch frames; retained custody evidence for flagged recovery."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

CAPTURE_BYTES = 16_384
STAGES = ('paste-end', 'enter-sent', 'verify')
RETRY_STAGES = ('retry-check', 'retry-enter-sent')


class Trace:
    def __init__(self, root, pane, text):
        self.path = (Path(root) / 'ephemeral' /
                     f'{pane.removeprefix("st-")}.submission-{uuid.uuid4().hex}.jsonl')
        self.pane = pane
        self.body_sha256 = hashlib.sha256(text.encode()).hexdigest()
        self.seen = set()
        self.identity = None

    def capture(self, stage, capture, *, key=None, outcome=None):
        """At most five frames, 16 KiB each. Return only retained evidence."""
        if stage not in STAGES + RETRY_STAGES or stage in self.seen:
            return
        self.seen.add(stage)
        row = dict(schema=1, stage=stage, pane=self.pane,
                   body_sha256=self.body_sha256,
                   at=datetime.now(timezone.utc).isoformat(), monotonic_ns=time.monotonic_ns())
        if key is not None:
            row['key'] = key
        if outcome is not None:
            row['outcome'] = outcome
        try:
            screen = capture(self.pane, attrs=True, timeout=0.5)
            encoded = screen.encode('utf-8')
            row['screen_bytes'] = len(encoded)
            row['truncated'] = len(encoded) > CAPTURE_BYTES
            row['screen'] = encoded[-CAPTURE_BYTES:].decode('utf-8', errors='ignore')
        except Exception as exc:  # observation must not become a delivery gate
            row['capture_error'] = type(exc).__name__
        row['capture_finished_monotonic_ns'] = time.monotonic_ns()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_APPEND
            flags |= os.O_CREAT | os.O_EXCL if self.identity is None else 0
            fd = os.open(self.path, flags, 0o600)
            try:
                meta = os.fstat(fd)
                identity = (meta.st_dev, meta.st_ino)
                if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                        or meta.st_nlink != 1 or stat.S_IMODE(meta.st_mode) != 0o600
                        or self.identity is not None and identity != self.identity):
                    raise OSError('unsafe trace file')
                self.identity = identity
                with os.fdopen(fd, 'a', encoding='utf-8', closefd=False) as stream:
                    stream.write(json.dumps(row, ensure_ascii=True) + '\n')
            finally:
                os.close(fd)
        except Exception as exc:
            print(f'  warning: Codex submission trace {stage} not retained '
                  f'({type(exc).__name__})', file=sys.stderr)
            return None
        return row


def for_launch(root, pane, text):
    """Default on for ephemeral panes; no screen collection for other sends."""
    if root and re.fullmatch(r'st-eph-[a-z]+-[a-z0-9]+', pane):
        return Trace(root, pane, text)
    return None
