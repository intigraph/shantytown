"""Execute the projected hook and inspect its complete model-context payload."""
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from shantytown import codex, resume_brief, runtime


@pytest.mark.parametrize('harness', ['claude', 'codex'])
def test_projected_resume_hook_delivers_checkpoint_as_json_once(tmp_path, harness):
    checkpoint = 'TZ9P-CHECKPOINT: preserve "quoted" text and Unicode 🦕\nnext operation'
    text = resume_brief.compose('fixture-reader', checkpoint=checkpoint,
        checkpoint_bead='fixture-item', quipu_nodes=['urn:fixture:tz9p'],
        docs=['docs/handoff.md'])
    resume_brief.Briefs(tmp_path).put('fixture-reader', text)
    groups = (runtime.session_start_hooks(tmp_path) if harness == 'claude'
              else codex.settings_for_role('worker', root=tmp_path)['hooks']['SessionStart'])
    hook = next(h for g in groups for h in g['hooks']
                if 'shantytown.resume_brief' in h['command'])
    env = dict(os.environ, SHANTY_ROOT=str(tmp_path), SHANTY_AGENT='fixture-reader',
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    def run():
        return subprocess.run(shlex.split(hook['command']), env=env, input='{}',
                              capture_output=True, text=True, timeout=10, check=True)
    result = run()
    output = json.loads(result.stdout)['hookSpecificOutput']
    assert output['hookEventName'] == 'SessionStart'
    assert output['additionalContext'] == text
    assert checkpoint in output['additionalContext']
    for pointer in ['fixture-item', 'urn:fixture:tz9p', 'docs/handoff.md']:
        assert pointer in output['additionalContext']
    assert not result.stderr
    assert run().stdout == ''
    assert resume_brief.Briefs(tmp_path).peek('fixture-reader') is None
