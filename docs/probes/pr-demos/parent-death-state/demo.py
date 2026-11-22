import runpy, subprocess
from pathlib import Path
namespace = dict(runpy.run_path('tests/test_crew_display_protocol.py'))
before = dict(namespace)
exec(compile(subprocess.check_output(['git', 'show', 'a21237ab:tests/test_crew_display_protocol.py'], text=True), 'baseline', 'exec'), before)
original = Path.read_text
try:
 for state in ('S', 'Z', 'X', 'x'):
  Path.read_text = lambda self: namespace['_fake_proc_stat'](12345, state)
  print(f"state={state}: before_running={before['_process_running'](12345)} after_running={namespace['_process_running'](12345)}")
finally:
 Path.read_text = original
