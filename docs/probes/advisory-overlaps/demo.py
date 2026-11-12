"""Same isolated forge fixture on the exact base and current source; no network."""
from copy import deepcopy
from pathlib import Path
import subprocess
import types

from shantytown import pr_preflight as current

BASE = '41bbe614d12057b582f70314cbb2e37fe2bff9dc'
ROOT = Path(__file__).resolve().parents[3]
baseline = types.ModuleType('shantytown._overlap_baseline')
baseline.__package__ = 'shantytown'
exec(compile(subprocess.check_output(
    ['git', 'show', f'{BASE}:shantytown/pr_preflight.py'], cwd=ROOT),
    '<exact-base>', 'exec'), baseline.__dict__)

# Reuse the checked-in forge fixture; it records POSTs instead of making them.
fixture = types.ModuleType('fixture')
exec(compile((ROOT/'tests/test_pr_preflight.py').read_text(), '<forge-fixture>', 'exec'), fixture.__dict__)


def probe(module, kind):
    row = fixture.pull()
    if kind == 'release':
        row['user'] = {'login': 'release-plz[bot]', 'type': 'Bot'}
    rows = [] if kind == 'disjoint' else [row]
    if kind == 'duplicate':
        row['head']['ref'] = 'feature'
    forge = fixture.Forge(rows)
    original = module.candidate
    module.candidate = lambda *args: {
        'head': fixture.HEAD, 'head_ref': 'feature', 'base': fixture.BASE,
        'base_ref': 'main', 'files': ['src/shared.py']}
    try:
        result = module.run('unused', fixture.REPO, 'main', 'project-new',
                            'Concrete change', 'New work', [], create=True, api=forge)
        print(f"{kind}: created={bool(result['created'])} POSTs={len(forge.writes)} "
              f"draft={forge.writes[0]['draft']} overlaps={len(result['overlaps'])}")
        if result['overlaps']:
            assert 'Advisory: PR #1' in forge.writes[0]['body']
    except module.Refused as error:
        print(f'{kind}: REFUSED ({error}) POSTs={len(forge.writes)}')
        return False
    finally:
        module.candidate = original
    return True


if __name__ == '__main__':
    print(f'BASE {BASE}; target: isolated synthetic forge, no network writes')
    assert not probe(baseline, 'ordinary')
    assert not probe(baseline, 'release')
    print('CANDIDATE source: same inputs, no dispositions')
    assert probe(current, 'ordinary')
    assert probe(current, 'release')
    assert probe(current, 'disjoint')
    assert not probe(current, 'duplicate')
    print('Candidate overlap creation refusals: 0/2; duplicate control remains refused')
