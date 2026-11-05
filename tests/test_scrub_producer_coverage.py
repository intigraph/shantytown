"""Producer scratch custody changes coverage accounting, never guard arming."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-scrub-guard.sh"


class ProducerCoverage(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.home = Path(self.sandbox.name) / "home"
        self.home.mkdir()
        self.metrics = self.home / "coverage.prom"
        config = self.home / "scrub.conf"
        config.write_text("internal_host_re=forge\\.invalid\n")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=str(self.home), SCRUB_PATTERNS_FILE=str(config),
                        SCRUB_GUARD_SOURCE_DIR=str(self.home / "guard"),
                        SCRUB_GUARD_TEXTFILE=str(self.metrics),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                        GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        self.real = self.init_repo(self.home / "persistent")
        self.root = self.home / ".local/state/quipu-share-producer/quechua/source-abcd1234"
        self.root.mkdir(parents=True, mode=0o700)
        self.scratch = self.init_repo(self.root / "source")

    def git(self, *args):
        return subprocess.run(["git", *map(str, args)], env=self.env,
                              check=True, capture_output=True, text=True)

    def init_repo(self, path):
        self.git("init", "-q", path)
        self.git("-C", path, "remote", "add", "origin", "https://example.org/public.git")
        return path

    def sweep(self, check=False, expected=0, root=None):
        args = ["bash", str(SCRIPT), "--root", str(root or self.home)]
        if check:
            args.append("--check")
        result = subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return {line.split()[0]: int(line.split()[1]) for line in self.metrics.read_text().splitlines()
                if line and not line.startswith("#") and "{" not in line}

    def test_scratch_cleanup_keeps_persistent_series_and_real_removal_changes_it(self):
        before = self.sweep()
        self.assertEqual(before["scrub_guard_repos_total"], 2)
        self.assertEqual(before["scrub_guard_persistent_repos_total"], 1)
        self.assertEqual(before["scrub_guard_ephemeral_repos_total"], 1)
        self.assertEqual(before["scrub_guard_armed_total"], 2)
        self.assertTrue((self.scratch / ".git/hooks/pre-push").is_symlink())
        shutil.rmtree(self.root)
        after = self.sweep(check=True)
        self.assertEqual(after["scrub_guard_repos_total"], 1)
        self.assertEqual(after["scrub_guard_persistent_repos_total"], 1)
        self.assertEqual(after["scrub_guard_ephemeral_repos_total"], 0)
        self.assertEqual(after["scrub_guard_missing_total"], 0)
        shutil.rmtree(self.real)
        empty = self.sweep(check=True)
        self.assertEqual(empty["scrub_guard_persistent_repos_total"], 0)

    def test_unarmed_scratch_is_still_a_gap(self):
        self.sweep()
        (self.scratch / ".git/hooks/pre-push").unlink()
        result = self.sweep(check=True, expected=1)
        self.assertEqual(result["scrub_guard_ephemeral_repos_total"], 1)
        self.assertEqual(result["scrub_guard_missing_total"], 1)

    def test_nonprivate_or_lookalike_root_stays_persistent(self):
        self.root.chmod(0o755)
        result = self.sweep()
        self.assertEqual(result["scrub_guard_persistent_repos_total"], 2)
        self.assertEqual(result["scrub_guard_ephemeral_repos_total"], 0)
        self.root.chmod(0o700)
        self.root.rename(self.root.with_name("source-not-a-random-run"))
        self.assertEqual(self.sweep()["scrub_guard_ephemeral_repos_total"], 0)

    def test_external_hooks_stay_persistent(self):
        hooks = self.home / "external-hooks"
        hooks.mkdir()
        self.git("-C", self.scratch, "config", "core.hooksPath", hooks)
        result = self.sweep()
        self.assertEqual(result["scrub_guard_persistent_repos_total"], 2)
        self.assertEqual(result["scrub_guard_ephemeral_repos_total"], 0)

    def test_symlinked_run_root_stays_persistent(self):
        physical = self.home / "persistent-source"
        self.root.rename(physical)
        self.root.symlink_to(physical, target_is_directory=True)
        result = self.sweep(root=self.root)
        self.assertEqual(result["scrub_guard_persistent_repos_total"], 1)
        self.assertEqual(result["scrub_guard_ephemeral_repos_total"], 0)

    def test_shared_persistent_repository_stays_persistent(self):
        shutil.rmtree(self.scratch)
        self.git("-C", self.real, "-c", "user.name=Test", "-c", "user.email=test@example.org",
                 "commit", "--allow-empty", "-qm", "fixture")
        self.git("-C", self.real, "worktree", "add", "-q", self.scratch, "-b", "scratch")
        # Even when only the producer-looking worktree is in this sweep's scope,
        # its persistent common hooks must remain visible to the shrink alert.
        result = self.sweep(root=self.root)
        self.assertEqual(result["scrub_guard_persistent_repos_total"], 1)
        self.assertEqual(result["scrub_guard_ephemeral_repos_total"], 0)

    def test_scratch_common_with_external_worktree_stays_persistent(self):
        self.git("-C", self.scratch, "-c", "user.name=Test", "-c", "user.email=test@example.org",
                 "commit", "--allow-empty", "-qm", "fixture")
        linked = self.home / "persistent-linked"
        self.git("-C", self.scratch, "worktree", "add", "-q", linked, "-b", "persistent")
        # A scratch-first sweep deduplicates the common Git directory before
        # it can discover the outside checkout. Classification must therefore
        # inspect shared custody even when only the scratch root is swept.
        scoped = self.sweep(root=self.root)
        self.assertEqual(scoped["scrub_guard_persistent_repos_total"], 1)
        self.assertEqual(scoped["scrub_guard_ephemeral_repos_total"], 0)
        whole = self.sweep()
        self.assertEqual(whole["scrub_guard_persistent_repos_total"], 2)
        self.assertEqual(whole["scrub_guard_ephemeral_repos_total"], 0)


if __name__ == "__main__":
    unittest.main()
