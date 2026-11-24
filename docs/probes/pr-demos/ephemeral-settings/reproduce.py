"""Show configuration retirement without launching an agent or touching live data."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from shantytown import ephemeral
from shantytown.hook_bundles import emitted_role_files

with tempfile.TemporaryDirectory(prefix='st-retired-settings-') as directory:
    root = Path(directory)
    name = 'eph-task-abcdef'
    ephemeral.write(root, dict(name=name, state=ephemeral.DONE, harness='codex'))
    config = root / 'settings' / 'codex' / ('agent-' + name) / 'config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('# emitted configuration\n')
    history = config.parent / 'history.jsonl'
    history.write_text('retained job history\n')
    print('BEFORE unknown-role hook files:', len(emitted_role_files(root)[1]))
    print('DRY RUN:', ephemeral.reap(root, pane_alive=lambda _: False,
                                      end=lambda *a: None, now=0, dry_run=True))
    print('AFTER:', ephemeral.reap(root, pane_alive=lambda _: False,
                                    end=lambda *a: None, now=0))
    print('AFTER unknown-role hook files:', len(emitted_role_files(root)[1]))
    print('Archived config preserved:', config.with_name('config.toml.retired').read_text()
          == '# emitted configuration\n')
    print('Job history preserved:', history.read_text() == 'retained job history\n')
