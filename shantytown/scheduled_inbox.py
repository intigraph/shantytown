"""One fixed durable inbox action for Chaski's result-descriptor executor.

No scheduling, signing, retries or graph-provided commands. The signed receiver
must claim the slot before starting this child. Uncertainty emits no receipt.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys

RESULT_FD_ENV = 'ST_SCHEDULED_RESULT_FD'


def _result_fd() -> int:
    raw = os.environ.get(RESULT_FD_ENV, '')
    if not re.fullmatch(r'[0-9]{1,10}', raw):
        raise ValueError('writable anonymous result pipe required')
    fd = int(raw)
    if (not 3 <= fd <= 2147483647 or not stat.S_ISFIFO(os.fstat(fd).st_mode) or
            fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY):
        raise ValueError('writable anonymous result pipe required')
    return fd


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--backend', required=True, choices=('seeds', 'files'))
    parser.add_argument('--registry', required=True, choices=('quipu', 'files', 'toml'))
    parser.add_argument('--sender', required=True)
    parser.add_argument('--recipient', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--message', required=True)
    args = parser.parse_args(argv)
    try:
        fd = _result_fd()
        root = Path(args.root)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError('explicit existing absolute deployment root required')
        for name in (args.sender, args.recipient, args.job):
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}', name):
                raise ValueError('bounded sender, recipient and job names required')
        if os.environ.get('SHANTY_AGENT') != args.sender:
            raise ValueError('pinned sender differs from explicit child environment')
        if not args.message.strip() or len(args.message.encode('utf-8')) > 4096:
            raise ValueError('bounded nonempty message required')
    except (ValueError, OSError):
        print('scheduled inbox: preconditions unavailable; no result', file=sys.stderr)
        return 2

    from . import cli
    try:
        # Reuse the actual command, including persist-first routing, attribution,
        # normal pane submission/readback and journal. Never read local job TOML.
        code = cli.main(['--root', str(root), '--backend', args.backend,
                         '--registry', args.registry, 'inbox', args.recipient, '-d',
                         f'[job {args.job}] {args.message}'])
    except (Exception, SystemExit):
        print('scheduled inbox: delivery uncertain; no result', file=sys.stderr)
        return 2
    if type(code) is not int or code not in (0, 1):
        # A persist request may have committed before its response was lost.
        # Let the outer receiver preserve UNKNOWN, never label this retryable.
        print('scheduled inbox: delivery uncertain; no result', file=sys.stderr)
        return 2
    result = json.dumps({'schema_version': 1,
                         'outcome': 'succeeded' if code == 0 else 'failed',
                         'exit_code': code}, separators=(',', ':')).encode()
    try:
        if os.write(fd, result) != len(result):
            raise OSError('short result write')
    except OSError:
        print('scheduled inbox: result receipt unavailable; do not repeat delivery',
              file=sys.stderr)
        return 2
    return code


if __name__ == '__main__':
    raise SystemExit(main())
