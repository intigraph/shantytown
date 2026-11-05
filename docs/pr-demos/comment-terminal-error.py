"""Offline adapter demonstration; no tracker process or network is invoked."""
import subprocess
from pathlib import Path
from types import ModuleType

from shantytown import br, stats

BASE = '2981a4ebc808356d5aef9ff600c606ac7bdbcc71'


class Tracker:
    _tool = 'sd'
    repo = None

    def __init__(self, code):
        self.code = code
        self.writes = 0

    def _bd_for(self, item, *args):
        self.writes += 1
        warning = ('sd: actor/principal mismatch (observe): actor="worker" '
                   'principal="shared-writer" verb="comments add" ' + 'x' * 180)
        return subprocess.CompletedProcess(args, self.code, '', warning +
            '\nsd: quipu 503: write outcome UNKNOWN; inspect readback before retrying')


def show(label, module):
    print(label)
    tracker = Tracker(1)
    try:
        module.append_comment(tracker, 'task-1', 'synthetic checkpoint')
    except RuntimeError as error:
        print(error)
        text = str(error)
    else:
        raise AssertionError('failure was swallowed')
    print(f'write attempts: {tracker.writes}')
    assert tracker.writes == 1
    print()
    return text


def main():
    # Avoid consulting even local credential files during the offline demo.
    stats._known_quipu_bearers = lambda: ()
    source = subprocess.check_output(['git', 'show', f'{BASE}:shantytown/br.py'], text=True)
    old = ModuleType('shantytown._demo_base_br')
    old.__package__ = 'shantytown'
    exec(compile(source, '<base br.py>', 'exec'), old.__dict__)
    before = show(f'BASE {BASE}', old)
    after = show('CANDIDATE (current source checkout)', br)
    assert 'quipu 503' not in before and 'exit 1' not in before
    assert 'quipu 503' in after and 'exit 1' in after
    # A zero exit with an observe warning remains success.
    success = Tracker(0)
    br.append_comment(success, 'task-1', 'synthetic checkpoint')
    assert success.writes == 1
    print('CONTROL: observe warning + exit 0 accepted; one write, no retry')


if __name__ == '__main__':
    main()
