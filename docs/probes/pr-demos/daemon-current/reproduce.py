"""Local package-pointer demonstration; no installed Codex or service calls."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def load(ref, directory):
    source = subprocess.check_output(
        ['git', 'show', f'{ref}:shantytown/codex_packages.py'])
    path = directory / 'packages.py'
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location('fixture_packages', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Only mount classification is modeled. File operations and locks are real.
    module.filesystem = lambda path: 'ext4'
    return module


def probe(ref):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        module = load(ref, root)
        home, durable = root/'runtime'/'card', root/'disk'/'daemon'
        module.prepare(home, durable)
        binary = durable/'releases'/'version'/'bin'/'codex'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'persistent fixture payload')
        current = durable/'current'
        # Model the native updater's observed write through its per-card alias.
        current.symlink_to(home/'packages'/'app-server-daemon'/'releases'/'version')
        module.prepare(home, durable)
        shutil.rmtree(home)
        resolved = (current/'bin'/'codex').is_file()
        relative = not os.path.isabs(os.readlink(current))
        return resolved, relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='4ac176316eea10d55745d1f7c3f72a70e777acc6')
    parser.add_argument('--candidate', default='HEAD')
    args = parser.parse_args()
    print('Target: isolated files; modeled native updater and mount classification.')
    print('Trigger: rewrite current through runtime alias, provision, erase runtime home.')
    for label, ref, expected in [('BEFORE', args.base, (False, False)),
                                 ('AFTER', args.candidate, (True, True))]:
        sha = subprocess.check_output(['git', 'rev-parse', ref], text=True).strip()
        resolved, relative = probe(ref)
        print(f'{label} {sha}: payload={"resolvable" if resolved else "MISSING"}; '
              f'current={"relative" if relative else "absolute runtime alias"}')
        assert (resolved, relative) == expected
    print('PASS: the same selected disk payload survives runtime cleanup after the fix.')


if __name__ == '__main__':
    main()
