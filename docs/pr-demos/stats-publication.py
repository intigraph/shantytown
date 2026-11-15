"""Compare real stats.capture calls with an isolated in-memory graph transport."""
import argparse
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

PROBE = r'''
import importlib.util, sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location('publication_fixture', sys.argv[2])
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
    world = f.world.__wrapped__(Path(directory), patch)
    capture, reads = f._stats_publisher(world, patch)
    capture(101)
    initial = len(reads)
    for at in range(102, 202): capture(at)
    unchanged = len(reads) - initial
    capture(400)
    due = len(reads) - initial - unchanged
    print(f'{sys.argv[3]}: initial reads={initial}; 100 unchanged hooks add={unchanged}; due heartbeat adds={due}', flush=True)
    assert due > 0, 'due heartbeat must publish'
    assert len(world[2].facts) == 2
    if sys.argv[3] == 'candidate': assert unchanged == 0
    else: assert unchanged == 100
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='48bb2a84b566cf107214057c4a5e1d05a928080d')
    args = parser.parse_args()
    root = Path.cwd()
    fixture = root / 'tests/test_owned_work_graph.py'
    print('Isolated source fixture: actual stats.capture; fake graph transport; no network.', flush=True)
    print('Baseline revision: ' + args.baseline, flush=True)
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        archive = base / 'source.tar'
        subprocess.run(['git', 'archive', '--format=tar', args.baseline, '-o', str(archive)], check=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(base / 'source', filter='data')
        for label, source in [('baseline', base / 'source'), ('candidate', root)]:
            subprocess.run([sys.executable, '-c', PROBE, str(source), str(fixture), label], check=True)
    print('Control: both revisions publish the due heartbeat; candidate preserves two immutable facts.', flush=True)


if __name__ == '__main__':
    main()
