"""Same SDK adapter probe on base/head; every child runner is a private stub."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading

# Run from the selected source root. For a base export, copy this script and
# the head's fully stubbed test fixture into that export (see README).
sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / 'tests')]
import pytest
from shantytown import seeds_read_cache as cache
from test_sd_stale_singleflight import sdk, call


def cohort(mode):
    with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
        tracker, state = sdk.__wrapped__(Path(directory), patch)
        state['mode'] = mode
        barrier = threading.Barrier(8)
        def read(_):
            with cache.stale_ok():
                barrier.wait(timeout=5)
                result = call(tracker)
                return result.returncode
        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(read, range(8)))
        expected = 0 if mode == 'ok' else None
        assert all(code == expected for code in codes) if expected is not None else all(codes)
        print(json.dumps(dict(mode=mode, callers=8, stubbed_child_dispatches=state['calls'],
                              successful_answers=codes.count(0), refusals=sum(c != 0 for c in codes))))
        before = state['calls']
        state['mode'] = 'ok'
        with cache.exact_reads():
            assert call(tracker).returncode == 0
        print(json.dumps(dict(exact_read_additional_dispatches=state['calls'] - before)))


if __name__ == '__main__':
    print('SDK adapter source fixture; no real child process or remote store')
    print(json.dumps(dict(sd_source_sha256=hashlib.sha256(
        Path('shantytown/sd.py').read_bytes()).hexdigest())))
    cohort('ok')
    cohort('failure')
