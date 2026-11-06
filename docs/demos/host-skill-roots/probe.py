"""Offline source-root binding probe; no graph, credentials or host writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from shantytown import tooling

BASE = '3e5aa09852c051444384b44399b44fd2449beff1'
RUNTIME = 'ccc2cd2b'
repo = Path(__file__).resolve().parents[3]
with tempfile.TemporaryDirectory() as directory:
    sandbox = Path(directory)
    source = sandbox / 'before.py'
    source.write_bytes(subprocess.check_output(
        ['git', 'show', f'{BASE}:shantytown/tooling.py'], cwd=repo))
    spec = importlib.util.spec_from_file_location('shantytown._before_tooling', source)
    before = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = before
    spec.loader.exec_module(before)
    roots = {'SHANTY_SKILL_SOURCE_ROOT': sandbox / 'toolkit',
             'CAMAYOC_SRC': sandbox / 'camayoc'}
    config = sandbox / 'deployment'
    config.mkdir()
    (config / 'shantytown.toml').write_text('[env]\n' + ''.join(
        f'{key}={json.dumps(str(value))}\n' for key, value in roots.items()))
    skills = {f'skill{i:02}': f'${{SHANTY_SKILL_SOURCE_ROOT}}/skills/skill{i:02}'
              for i in range(26)}
    skills['camayoc'] = '${CAMAYOC_SRC}/camayoc/skills/camayoc'
    absolute = {}
    for name, reference in skills.items():
        key, suffix = reference[2:].split('}/', 1)
        target = roots[key] / suffix
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text('# Fixture\n')
        absolute[name] = str(target)
    document = {'version': 1, 'mcpServers': {}, 'skills': skills,
                'instructions': 'Use the declared skills.'}
    raw = json.dumps(document)
    old = before.parse(raw, 'urn:example:tooling')
    new = tooling.parse(raw, 'urn:example:tooling', root=config)
    available = lambda m: sum((p / 'SKILL.md').is_file() for _, p in m.sources(sandbox))
    print(f'Base {BASE[:8]} / candidate runtime {RUNTIME}; isolated fixture')
    print(f'Same portable manifest, before: {available(old)}/27 available')
    print(f'Same portable manifest, after:  {available(new)}/27 available')
    assert available(old) == 0 and available(new) == 27
    document['skills'] = absolute
    legacy = before.parse(json.dumps(document), 'urn:example:tooling')
    encoded = lambda m: json.dumps([(n, str(p)) for n, p in m.sources(sandbox)]).encode()
    assert encoded(legacy) == encoded(new)
    print('Legacy host projection byte-identical: yes')
    print('Projection digest:', hashlib.sha256(encoded(new)).hexdigest())
    missing = next(iter(new.sources(sandbox)))[1] / 'SKILL.md'
    missing.unlink()
    assert available(new) == 26
    print('Missing local SKILL.md positive control: 26/27 available; unchanged availability gate refuses')
