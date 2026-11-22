"""Execute the actual workflow shell with a synthetic gate, never a service."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(Path('/usr/bin/python3').is_file(), 'Linux controller workflow')
class WorkflowGateTests(unittest.TestCase):
    def setUp(self):
        workflow = (ROOT/'.github/workflows/service-admission.yml').read_text()
        self.shell = textwrap.dedent(workflow.split('        run: |\n', 1)[1])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gate = self.root/'gate.py'
        self.gate.write_text('import json,os,sys\nprint(json.dumps(sys.argv[1:]))\n'
                             'raise SystemExit(int(os.environ.get("FIXTURE_EXIT", "0")))\n')

    def run_gate(self, **overrides):
        env = dict(os.environ, ADMISSION_GATE=str(self.gate), ADMISSION_REPO='example/project',
                   ADMISSION_GROUP='a'*40, ADMISSION_BASE='b'*40,
                   ADMISSION_REF='refs/heads/gh-readonly-queue/main/pr-1-'+'c'*40)
        env.update(overrides)
        return subprocess.run(['bash', '-c', self.shell], cwd=self.root, env=env,
                              capture_output=True, text=True, timeout=10)

    def test_missing_relative_and_symlink_gate_refuse(self):
        link = self.root/'linked.py'; link.symlink_to(self.gate)
        for path in ('', 'gate.py', str(self.root/'missing.py'), str(link)):
            with self.subTest(path=path): self.assertNotEqual(self.run_gate(ADMISSION_GATE=path).returncode, 0)

    def test_gate_refusal_propagates_to_job_failure(self):
        result = self.run_gate(FIXTURE_EXIT='1')
        self.assertEqual(result.returncode, 1)

    def test_event_values_are_literal_arguments_never_shell_code(self):
        value = 'example/repo"; touch injected; #'
        result = self.run_gate(ADMISSION_REPO=value)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[1], value)
        self.assertFalse((self.root/'injected').exists())

    def test_isolated_python_does_not_load_checkout_or_pythonpath_modules(self):
        (self.root/'json.py').write_text('raise RuntimeError("candidate module executed")\n')
        result = self.run_gate(PYTHONPATH=str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0], '--repo')
