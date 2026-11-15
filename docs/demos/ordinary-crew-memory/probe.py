"""Same read against an ordinary-only transport before/after. No network I/O."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.error import HTTPError

from shantytown import memory_remote

BASE = '935220342d9219d26da493a46f2745f9bd5fecca'
ROOT = Path(__file__).resolve().parents[3]


class OrdinaryOnly:
    def __init__(self):
        self.paths = []

    def open(self, request, timeout):
        path = request.full_url.removeprefix('https://example.test')
        self.paths.append(path)
        if path != '/query':
            raise HTTPError(request.full_url, 404, 'no memory service', {}, None)
        assert 'GRAPH <urn:shantytown:crew-files:' in json.loads(request.data)['query']
        response = io.BytesIO(b'{"rows":[],"count":0,"truncated":false}')
        response.status = 200
        return response


def main():
    original = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':shantytown/memory_remote.py'])
    with tempfile.TemporaryDirectory(prefix='ordinary-memory-demo-') as directory:
        path = Path(directory) / 'base.py'
        path.write_bytes(original)
        spec = importlib.util.spec_from_file_location('shantytown._memory_demo_base', path)
        base = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = base
        spec.loader.exec_module(base)
        for label, module in [('base', base), ('candidate', memory_remote)]:
            opener = OrdinaryOnly()
            owner = module.Owner('urn:example:deployment', 'urn:example:project', 'urn:example:alpha')
            try:
                result = module.Client('https://example.test', owner, opener=opener).read()
            except module.Unproven:
                assert label == 'base'
                print('base: /memory/read -> 404/refused; no supported round-trip')
            else:
                assert label == 'candidate' and result is None
                print('candidate: /query -> complete explicit owner graph, absent head')
            print(label + ' endpoints: ' + ', '.join(opener.paths))
    print('Populated exact-byte, CAS-race and replay controls: tests/test_memory_graph.py')
    print('Synthetic transcript only. Installed Quipu primitive-removal, native harness and private migration acceptance remain separate.')


if __name__ == '__main__':
    main()
