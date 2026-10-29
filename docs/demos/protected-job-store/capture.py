import subprocess
import sys
for source in ('demo-base', '.'):
    command = [sys.executable, '-I', 'docs/demos/protected-job-store/run.py', '--source', source]
    print('$ python3 -I docs/demos/protected-job-store/run.py --source ' + source, flush=True)
    subprocess.run(command, check=True)
