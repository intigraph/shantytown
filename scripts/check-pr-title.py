#!/usr/bin/env python3
"""Keep squash subjects parseable by release-please (aegis-xa8)."""
import json
import os
from pathlib import Path
import re
import sys

TYPES = ('feat', 'fix', 'perf', 'refactor', 'docs', 'test', 'chore', 'ci', 'build')
TITLE = re.compile(r'(' + '|'.join(TYPES) + r')(\([^()\s][^()\r\n]*\))?!?: [^\s].*')
TRACKER_ID = re.compile(r'(?<![\w-])(?:aegis|hq|gassy|qp)-[a-z0-9]{3,}(?:\.[0-9]+)*(?![\w-])')


def valid(title):
    return (isinstance(title, str) and '\n' not in title and '\r' not in title
            and TITLE.fullmatch(title) is not None and not TRACKER_ID.search(title))


def main():
    if os.environ.get('GITHUB_EVENT_NAME') != 'pull_request':
        print('PR title check: not a pull_request event')
        return 0
    try:
        title = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['pull_request']['title']
    except (KeyError, OSError, ValueError, TypeError):
        print('PR title check: cannot read pull_request.title', file=sys.stderr)
        return 1
    if not valid(title):
        print('PR title must use type(scope): summary or type: summary without tracker IDs; '
              'retitle visibly; types: ' + ', '.join(TYPES), file=sys.stderr)
        return 1
    print('PR title check: conventional subject accepted')
    return 0


if __name__ == '__main__':
    sys.exit(main())
