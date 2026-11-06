"""Replay a sanitized busy capture through baseline and candidate classifiers."""
import argparse
from pathlib import Path
import subprocess
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import triage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    source = subprocess.check_output(
        ['git', 'show', f'{args.base}:shantytown/triage.py'], text=True)
    baseline = ModuleType('baseline_triage')
    baseline.__package__ = 'shantytown'
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, 'baseline_triage.py', 'exec'), baseline.__dict__)
    screen = (ROOT / 'tests/fixtures/codex_input/busy-queue-wrapped.txt').read_text()
    print(f'Sanitized captured composer; base {args.base}; candidate working tree')
    for label, implementation in [('before', baseline), ('after', triage)]:
        print(f'{label}: input={implementation.input_state(screen)} '
              f'run={implementation.work_state(screen, True)}')
        print(f'{label}: unreadable control={implementation.input_state("› unreadable text")}')


if __name__ == '__main__':
    main()
