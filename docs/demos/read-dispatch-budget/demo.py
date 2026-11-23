"""Actual loopback HTTP dispatches, isolated source/caches; no remote store."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / 'tests')]
import pytest
from test_seeds_read_cache import service
from shantytown import seeds_plate, seeds_read_cache

CHILD = '''
import sys
from types import SimpleNamespace
from shantytown import seeds_plate, seeds_read_cache
sys.stdin.readline()
try:
    with seeds_read_cache.direct_reads():
        result = seeds_plate._query(SimpleNamespace(quipu_url=sys.argv[1]),
                                    "SELECT distinct-" + sys.argv[2], 5)
    assert result["rows"][0]["value"] == "before"
except ValueError:
    sys.exit(75)
sys.exit(0)
'''


def main():
    print('Native direct-read source fixture; actual HTTP on a private loopback server')
    print(json.dumps(dict(source_sha256=hashlib.sha256(
        Path('shantytown/seeds_plate.py').read_bytes()).hexdigest())))
    with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        with contextmanager(service.__wrapped__)(Path(directory), patch) as (proof, state):
            patch.setenv('ST_QUIPU_READS_PER_MINUTE', '2')
            children = [subprocess.Popen([sys.executable, '-c', CHILD, proof.quipu_url, str(n)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=dict(os.environ)) for n in range(3)]
            try:
                for child in children:
                    child.stdin.write('\n')
                    child.stdin.flush()
                codes = []
                for child in children:
                    out, err = child.communicate(timeout=10)
                    assert child.returncode in (0, 75), (out, err)
                    codes.append(child.returncode)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
            print(json.dumps(dict(configured_limit=2, processes=3,
                http_queries=state['queries'], populated_answers=codes.count(0),
                pre_dispatch_refusals=codes.count(75))))
            before = state['queries']
            patch.setenv('ST_QUIPU_READS_PER_MINUTE', '0')
            with seeds_read_cache.direct_reads():
                assert seeds_plate._query(proof, 'SELECT rollback-positive', 5)['rows']
            print(json.dumps(dict(rollback_off_additional_http_queries=state['queries'] - before)))


if __name__ == '__main__':
    main()
