"""Offline before/after demonstration using the regression's query fixture."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import pytest
from shantytown import sd, seeds_plate
from test_seeds_plate_projection import (
    test_refill_observation_ignores_unused_large_notes_but_keeps_park_gate as probe,
)

BASE = '2e85dd1431ff41ab2d320b0e00c97eaa3682ae02'
source = subprocess.check_output(['git', 'show', BASE + ':shantytown/sd.py'], text=True)
cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'SdTracker')
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'active_rows')
namespace = dict(vars(sd))
exec(compile(ast.Module(body=[method], type_ignores=[]), '<baseline-method>', 'exec'), namespace)
current = sd.SdTracker.active_rows
print('Target: offline wire fixture; one active item with 65,537-byte notes, one parked item')
print('Baseline:', BASE)
for phase, implementation in [('Before', namespace['active_rows']), ('After', current)]:
    with pytest.MonkeyPatch.context() as patch, tempfile.TemporaryDirectory() as folder:
        patch.setattr(sd.SdTracker, 'active_rows', implementation)
        patch.setattr(seeds_plate, 'uses_native_schema', lambda *a, **k: True)
        patch.setattr(seeds_plate, 'owner_shape_supported', lambda *a, **k: True)
        try:
            probe(Path(folder), patch)
        except AssertionError as error:
            if phase != 'Before':
                raise
            print(phase + ': reproduced failure:', error)
        else:
            if phase == 'Before':
                raise AssertionError('baseline unexpectedly accepted the fixture')
            print('After: observation written; parked item excluded; quiet-wait note cap still refuses')
