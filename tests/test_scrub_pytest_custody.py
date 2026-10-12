"""Real Git custody boundaries for disposable pytest coverage inventory."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class PytestCustody(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.addCleanup(self.sandbox.cleanup)
        self.home = Path(self.sandbox.name) / "home"
        self.home.mkdir()
        self.tmp = self.home / "short-tmp"
        self.tmp.mkdir(mode=0o700)
        self.parent = self.tmp / ("pytest-of-" + subprocess.check_output(["id", "-un"], text=True).strip())
        self.parent.mkdir(mode=0o700)
        self.generation = self.parent / "pytest-0"
        self.generation.mkdir(mode=0o700)
        (self.parent / "pytest-current").symlink_to(self.generation)
        self.repo = self.init_repo(self.generation / "fixture")
        script = (Path(__file__).resolve().parents[1] / "scripts/install-scrub-guard.sh").read_text()
        self.function = "is_owned_pytest_fixture() {" + script.split("is_owned_pytest_fixture() {", 1)[1].split("\nrepo_label()", 1)[0]

    def init_repo(self, path):
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        return path

    def excluded(self, path=None, prelude=""):
        result = subprocess.run(["bash", "-c", self.function + "\n" + prelude + '\nis_owned_pytest_fixture "$1"', "custody", str(path or self.repo)], env=dict(os.environ, HOME=str(self.home)), capture_output=True, text=True)
        self.assertIn(result.returncode, [0, 1], result.stderr)
        return result.returncode == 0

    def test_current_owned_generation(self):
        self.assertTrue(self.excluded())

    def test_older_retained_generation(self):
        newer = self.parent / "pytest-1"
        newer.mkdir(mode=0o700)
        (self.parent / "pytest-current").unlink()
        (self.parent / "pytest-current").symlink_to(newer)
        self.assertTrue(self.excluded())

    def test_adjacent_real_repository_remains(self):
        self.assertFalse(self.excluded(self.init_repo(self.parent / "production")))

    def test_similar_path_without_managed_link_remains(self):
        (self.parent / "pytest-current").unlink()
        self.assertFalse(self.excluded())

    def test_nonprivate_root_parent_generation_remain(self):
        for path in [self.tmp, self.parent, self.generation]:
            with self.subTest(path=path):
                path.chmod(0o755)
                self.assertFalse(self.excluded())
                path.chmod(0o700)
        self.assertTrue(self.excluded())

    def test_external_effective_hooks_remain(self):
        hooks = self.home / "real-hooks"
        hooks.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "config", "core.hooksPath", str(hooks)], check=True)
        self.assertFalse(self.excluded())

    def test_shared_repository_outside_generation_remains(self):
        external = self.init_repo(self.home / "real")
        subprocess.run(["git", "-C", str(external), "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "--allow-empty", "-qm", "initial"], check=True)
        worktree = self.generation / "shared"
        subprocess.run(["git", "-C", str(external), "worktree", "add", "-q", str(worktree)], check=True)
        self.assertFalse(self.excluded(worktree))

    def test_symlink_escape_remains(self):
        external = self.init_repo(self.home / "real")
        linked = self.generation / "linked"
        linked.symlink_to(external)
        self.assertFalse(self.excluded(linked))

    def test_current_link_escape_remains(self):
        external = self.home / "pytest-2"
        external.mkdir(mode=0o700)
        (self.parent / "pytest-current").unlink()
        (self.parent / "pytest-current").symlink_to(external)
        self.assertFalse(self.excluded())

    def test_wrong_owner_is_not_custody(self):
        self.assertFalse(self.excluded(prelude='stat() { if [[ "$*" == *"%u:%a"* ]]; then printf "99999:700\\n"; else command stat "$@"; fi; }'))


if __name__ == "__main__":
    unittest.main()
