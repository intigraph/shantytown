"""Same probe on the immutable base and candidate; no live agent or store."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
BASE = 'b431498a5663c0fe75761eeb809aff107809d55b'


def main():
    print('Synthetic stop: two owned seeds, including one P0/overdue; fake panes only.')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    print('Base:', BASE)
    print('Candidate source:', head)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('SHANTY_', 'ST_', 'QUIPU_'))}
    probe = ROOT / 'docs/demos/stopped-owner/probe.py'
    with tempfile.TemporaryDirectory(prefix='stopped-owner-demo-') as directory:
        baseline = Path(directory) / 'base'
        baseline.mkdir()
        data = subprocess.check_output(['git', 'archive', BASE], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            # The archive is the explicitly pinned local Git object.
            archive.extractall(baseline, filter='data')
        outputs = []
        for label, source in [('base', baseline), ('candidate', ROOT)]:
            print(f'\n$ python probe.py <{label} source>')
            result = subprocess.run([sys.executable, str(probe), str(source)],
                                    env=env, cwd=directory, text=True,
                                    capture_output=True, check=True)
            print(result.stdout, end='')
            output = json.loads(result.stdout.strip().splitlines()[-1])
            assert output['stop_exit'] == 0 and output['intent_recorded']
            assert output['owned_seed_positive_control'] == 2
            assert output['ownership_unchanged']
            outputs.append(output)
        assert outputs[0]['lead_escalations'] == 0
        assert outputs[1]['lead_escalations'] == 1 and outputs[1]['reported_seed_ids'] == ['fixture-a', 'fixture-b']
        print('\nPASS: 0 -> 1 batched escalation; both seeds retained; no ownership change.')
        print('Source fixture only: no installed or native Quipu/Brief acceptance claim.')


if __name__ == '__main__':
    main()
