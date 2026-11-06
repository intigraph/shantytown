"""Compare actual startup renders using offline identity and plate fixtures."""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import session_anchor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    baseline = ModuleType('baseline_anchor')
    baseline.__package__ = 'shantytown'
    source = subprocess.check_output(
        ['git', 'show', f'{args.base}:shantytown/session_anchor.py'], text=True)
    exec(compile(source, 'baseline_anchor.py', 'exec'), baseline.__dict__)
    primer_before = subprocess.check_output(
        ['git', 'show', f'{args.base}:shantytown/primer.md'], text=True)
    primer_after = (ROOT / 'shantytown/primer.md').read_text()
    print(f'Base: {args.base}; candidate: source checkout, offline fixture')
    for filename in ('session_anchor.py', 'primer.md', 'prime.py'):
        digest = hashlib.sha256((ROOT / 'shantytown' / filename).read_bytes()).hexdigest()
        print(f'Candidate {filename} sha256: {digest}')
    plate = '\n  You are fixture — worker.\nCurrent work: fixture-1.\n'
    with patch('shantytown.crew_memory.for_agent', return_value=''), \
            patch('shantytown.deployment.deployment_default', return_value=None):
        for label, module, primer in [('before', baseline, primer_before),
                                       ('after', session_anchor, primer_after)]:
            matches = len(re.findall(r'\b(?:camayoc|cy)\b', primer, re.I))
            print(f'\n{label}: packaged primer Camayoc/cy matches = {matches}')
            for rc, context in [(0, plate), (2, '')]:
                with patch.object(module, '_run_anchor', return_value=(rc, context)):
                    rendered = module.render('/fixture', 'fixture')
                print(f'{label}: anchor exit={rc}, stack-prime/1={"stack-prime/1" in rendered}, '
                      f'Camayoc skill={"Camayoc skill" in rendered}, '
                      f'map_question={"map_question" in rendered}')
                if label == 'after':
                    assert all(term in rendered for term in
                               ('stack-prime/1', 'Camayoc skill', 'cy prime --static',
                                'map_question', 'jev_dry_run'))
                    assert ('fixture-1' in rendered if rc == 0 else
                            'could not read your plate' in rendered)
            if label == 'after':
                print(rendered.split('[st stack primer', 1)[1].rstrip())
    print('\nNo live launch, service read, tool provisioning or memory write was performed.')


if __name__ == '__main__':
    main()
