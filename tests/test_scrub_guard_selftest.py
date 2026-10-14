#!/usr/bin/env python3
"""Run a guard only in owned disposable repositories; never contact a forge."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def snapshot(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def probe(guard, fault='none', number=1, empty=False, trace=None):
    with tempfile.TemporaryDirectory(prefix='scrub-selftest-') as temporary:
        root = Path(temporary)
        caller = root / 'caller'
        caller.mkdir()
        home = root / 'home'
        home.mkdir()
        bins = root / 'bin'
        bins.mkdir()
        fixtures = root / 'fixtures'
        fixtures.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                   GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
                   GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='maintenance.auto',
                   GIT_CONFIG_VALUE_0='false', GIT_CONFIG_KEY_1='gc.auto', GIT_CONFIG_VALUE_1='0',
                   SCRUB_PATTERNS_FILE=str(root / 'absent-config'), FAULT=fault,
                   FAULT_NUMBER=str(number), EMPTY_FAULT='1' if empty else '0',
                   FIXTURE_ROOT=str(fixtures), PROBE_ROOT=str(root),
                   REAL_GIT=shutil.which('git'), REAL_MKTEMP=shutil.which('mktemp'))
        if trace is not None:
            env['GIT_TRACE2_EVENT'] = str(trace)
        real_git = env['REAL_GIT']
        subprocess.run([real_git, 'init', '-q', str(caller)], env=env, check=True)
        for key, value in [('user.name', 'caller-control'), ('user.email', 'caller@example.invalid'),
                           ('core.hooksPath', os.devnull)]:
            subprocess.run([real_git, '-C', str(caller), 'config', key, value], env=env, check=True)
        (caller / 'sentinel').write_text('unchanged\n')
        subprocess.run([real_git, '-C', str(caller), 'add', 'sentinel'], env=env, check=True)
        subprocess.run([real_git, '-C', str(caller), 'commit', '-qm', 'caller control'], env=env, check=True)
        (bins / 'mktemp').write_text('''#!/usr/bin/env bash
n=0; [ ! -f "$PROBE_ROOT/alloc-count" ] || read -r n < "$PROBE_ROOT/alloc-count"
n=$((n+1)); echo "$n" > "$PROBE_ROOT/alloc-count"
if [ "$FAULT" = alloc ] && [ "$n" = "$FAULT_NUMBER" ]; then
  echo seen > "$PROBE_ROOT/fault-seen"
  if [ "$EMPTY_FAULT" != 1 ]; then mkdir "$FIXTURE_ROOT/rejected-$n"; echo "$FIXTURE_ROOT/rejected-$n"; fi
  exit 1
fi
case "$*" in
 *"$FIXTURE_ROOT/"*) exec "$REAL_MKTEMP" "$@" ;;
 *) exec "$REAL_MKTEMP" "$@" -p "$FIXTURE_ROOT" ;;
esac
''')
        (bins / 'git').write_text('''#!/usr/bin/env bash
case "${1:-}" in
 init|clone)
  kind=$1; n=0; file="$PROBE_ROOT/$kind-count"
  [ ! -f "$file" ] || read -r n < "$file"
  n=$((n+1)); echo "$n" > "$file"
  if [ "$FAULT" = "$kind" ] && [ "$n" = "$FAULT_NUMBER" ]; then echo seen > "$PROBE_ROOT/fault-seen"; exit 1; fi ;;
esac
exec "$REAL_GIT" "$@"
''')
        for p in bins.iterdir():
            p.chmod(0o755)
        bash_env = root / 'bash-env'
        bash_env.write_text('''cd() {
 if [ "$FAULT" = cd ] && [[ "${1:-}" == "$FIXTURE_ROOT/"* ]]; then
  local n=0; [ ! -f "$PROBE_ROOT/cd-count" ] || read -r n < "$PROBE_ROOT/cd-count"
  n=$((n+1)); echo "$n" > "$PROBE_ROOT/cd-count"
  if [ "$n" = "$FAULT_NUMBER" ]; then echo seen > "$PROBE_ROOT/fault-seen"; return 1; fi
 fi
 builtin cd "$@"
}
''')
        env.update(PATH=str(bins) + os.pathsep + os.environ['PATH'], BASH_ENV=str(bash_env))
        # Caller setup must not leave a maintenance child behind. Remove those
        # command-scope overrides for the guard so it proves its own isolation.
        guard_env = dict(env)
        for key in ('GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0',
                    'GIT_CONFIG_KEY_1', 'GIT_CONFIG_VALUE_1'):
            guard_env.pop(key)
        before = snapshot(caller)
        result = subprocess.run(['bash', str(guard.resolve()), '--selftest'], cwd=caller,
                                env=guard_env, capture_output=True, text=True, timeout=90)
        after = snapshot(caller)
        changes = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        return {'fault_seen': (root / 'fault-seen').exists(),
                'setup_counts': {k: int((root / (k + '-count')).read_text()) for k in ['alloc', 'init', 'clone', 'cd'] if (root / (k + '-count')).exists()},
                'fault': fault, 'number': number, 'empty': empty, 'exit': result.returncode,
                'caller_changes': changes, 'positive_controls': result.stdout.count('ok   '),
                'stdout': result.stdout, 'stderr': result.stderr}


class SelftestSetupFailureTests(unittest.TestCase):
    guard = Path(__file__).resolve().parents[1] / 'scripts' / 'pre-push-scrub-guard.sh'

    def assert_failure_is_contained(self, kind, number, empty=False):
        result = probe(self.guard, kind, number, empty)
        self.assertTrue(result['fault_seen'], result)
        self.assertNotEqual(result['exit'], 0, result)
        self.assertEqual(result['caller_changes'], [], result)

    def test_all_setup_failures_leave_caller_untouched(self):
        # All six allocations/initializations, three clones and five fixture
        # cd boundaries are exercised. Fault markers prevent vacuous passes.
        for kind, count in [('alloc', 6), ('init', 6), ('clone', 3), ('cd', 5)]:
            for number in range(1, count + 1):
                with self.subTest(kind=kind, number=number):
                    self.assert_failure_is_contained(kind, number)

    def test_empty_failed_allocations_leave_caller_untouched(self):
        for number in range(1, 7):
            with self.subTest(number=number):
                self.assert_failure_is_contained('alloc', number, empty=True)

    def test_populated_success_control_leaves_caller_untouched(self):
        with tempfile.TemporaryDirectory(prefix='scrub-git-trace-') as directory:
            trace = Path(directory) / 'trace.jsonl'
            result = probe(self.guard, trace=trace)
            events = [json.loads(line) for line in trace.read_text().splitlines()]
        self.assertTrue(any(e.get('event') == 'start' for e in events))
        maintenance = [e for e in events if e.get('event') == 'child_start'
                       and 'maintenance' in e.get('argv', [])]
        self.assertEqual(maintenance, [])
        self.assertEqual(result['exit'], 0, result)
        self.assertGreaterEqual(result['positive_controls'], 40, result)
        self.assertEqual(result['caller_changes'], [], result)
        self.assertEqual(result['setup_counts']['alloc'], 6, result)
        self.assertEqual(result['setup_counts']['init'], 6, result)
        self.assertEqual(result['setup_counts']['clone'], 3, result)


if __name__ == '__main__':
    unittest.main()
