"""Compare repeated policy decisions in private fixtures; no live hook or dispatch."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline-ref', default='4b48bce')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
probe = Path(__file__).with_name('probe.py')


def run(source):
    env = dict(os.environ, PYTHONPATH=str(source))
    result = subprocess.run([sys.executable, str(probe)], cwd=source, env=env,
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


archive = subprocess.check_output(['git', '-C', str(root), 'archive', args.baseline_ref])
with tempfile.TemporaryDirectory(prefix='event-waiting-') as baseline:
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(baseline, filter='data')
    before, after = run(baseline), run(root)
assert before['waiting']['prompt_count_per_10_turns'] == 10
assert after['waiting']['prompt_count_per_10_turns'] == 0
assert before['idle_control']['prompt_count_per_10_turns'] == after['idle_control']['prompt_count_per_10_turns'] == 10
assert before['near_control']['prompt_count_per_10_turns'] == after['near_control']['prompt_count_per_10_turns'] == 0
assert len(before['unsuitable_candidates']) == 2 and not after['unsuitable_candidates']
result = {'scope': 'private fixtures; ten identical synthetic admin turns, not live notification frequency',
          'baseline_ref': args.baseline_ref, 'before': before, 'after': after}
if args.output:
    args.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
