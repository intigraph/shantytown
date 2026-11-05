"""Inspect the actual resume producer on two revisions, without a model call."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def load(revision, index):
    source = subprocess.run(['git', 'show', revision + ':shantytown/resume_brief.py'],
                            check=True, capture_output=True, text=True).stdout
    name = 'shantytown._demo_resume_' + str(index)
    module = types.ModuleType(name)
    module.__package__ = 'shantytown'
    sys.modules[name] = module
    exec(compile(source, 'resume_brief.py@' + revision, 'exec'), module.__dict__)
    return module


def probe(module):
    with tempfile.TemporaryDirectory() as directory:
        checkpoint = 'Continue the saved operation: "quoted" text 🦕'
        text = module.compose('reader', checkpoint=checkpoint,
            checkpoint_bead='fixture-item', quipu_nodes=['urn:fixture:context'])
        briefs = module.Briefs(directory)
        briefs.put('reader', text)
        first, second = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, dict(SHANTY_ROOT=directory, SHANTY_AGENT='reader')):
            with contextlib.redirect_stdout(first):
                assert module.main([]) == 0
            with contextlib.redirect_stdout(second):
                assert module.main([]) == 0
        try:
            specific = json.loads(first.getvalue())['hookSpecificOutput']
        except json.JSONDecodeError as error:
            result = f'not a JSON envelope ({type(error).__name__}, column {error.colno})'
            visible = False
        else:
            assert specific['hookEventName'] == 'SessionStart'
            assert specific['additionalContext'] == text
            visible = True
            result = 'SessionStart additionalContext contains complete checkpoint + pointers'
        assert second.getvalue() == '' and briefs.peek('reader') is None
        print(result)
        print('second invocation: empty; pending brief: consumed')
        return visible


def main():
    results = []
    for index, revision in enumerate(sys.argv[1:]):
        print(f'{revision}: actual resume hook, isolated saved-brief fixture')
        results.append(probe(load(revision, index)))
    assert results == [False, True]
    print('Source output only; native Codex relaunch/injection acceptance remains separate.')


if __name__ == '__main__':
    main()
