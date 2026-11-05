"""Moved-owner origin admission uses real Git and a read-only forge fixture."""
import json
from pathlib import Path
import subprocess

import pytest

from shantytown import pr_preflight as p


CURRENT = "intigraph/yupana"
LEGACY = "scbrown/yupana"


@pytest.fixture
def moved(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(checkout), *args], text=True).strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (checkout / "source.txt").write_text("base\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-qb", "feature")
    (checkout / "source.txt").write_text("change\n")
    git("commit", "-qam", "change")
    head = git("rev-parse", "HEAD")
    git("remote", "add", "origin", "git@github.com:scbrown/yupana.git")

    data = tmp_path / "data"
    helper = data / "aegis-exec-src/scripts/lib/stack_repos.py"
    helper.parent.mkdir(parents=True)
    # Synthetic external CLI: exercise the adapter, not a second owner map.
    helper.write_text('''import json, sys
from pathlib import Path
assert sys.argv[1] == "canonical"
mapping = json.loads(Path(__file__).with_suffix(".json").read_text())
print(mapping.get(sys.argv[2], sys.argv[2]))
''')
    helper.with_suffix(".json").write_text(json.dumps({LEGACY: CURRENT}))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    return checkout, git, base, head, helper


class Forge:
    def __init__(self, base, head):
        self.base, self.head = base, head
        self.calls = []
        self.alias = {"id": 123, "full_name": CURRENT}
        self.alias_reads = 0

    def __call__(self, path, body=None):
        self.calls.append((path, body))
        assert body is None, "read-only preflight must not post"
        if path == f"repos/{CURRENT}":
            return {"id": 123, "full_name": CURRENT}
        if path == f"repos/{LEGACY}":
            self.alias_reads += 1
            return self.alias
        if path.endswith("/commits/feature"):
            return {"sha": self.head}
        if path.endswith("/commits/main"):
            return {"sha": self.base}
        assert path.startswith(f"repos/{CURRENT}/pulls?"), path
        return []


def preflight(moved, forge, **kwargs):
    return p.run(moved[0], CURRENT, "main", "project-new", "Concrete body",
                 "Concrete title", [], api=forge, **kwargs)


@pytest.mark.parametrize("origin", ["git@github.com:scbrown/yupana.git",
    "https://github.com/scbrown/yupana.git", "ssh://git@github.com/scbrown/yupana.git"])
def test_mapped_legacy_origin_passes_full_readonly_preflight(moved, origin):
    checkout, git, base, head, _ = moved
    git("remote", "set-url", "origin", origin)
    forge = Forge(base, head)
    report = preflight(moved, forge)
    assert report["candidate"]["head"] == head
    assert report["candidate"]["files"] == ["source.txt"]
    assert forge.alias_reads == 1
    assert git("remote", "get-url", "origin") == origin


def test_exact_origin_passes_without_optional_stack_helper(moved):
    _, git, base, head, helper = moved
    helper.unlink()
    git("remote", "set-url", "origin", "git@github.com:intigraph/yupana.git")
    assert preflight(moved, Forge(base, head))["candidate"]["head"] == head


@pytest.mark.parametrize("origin", ["git@github.com:foreign/yupana.git",
    "git@gitlab.com:scbrown/yupana.git", "git@github.com:scbrown/unmapped.git"])
def test_foreign_host_owner_or_unmapped_repo_refuses_with_fix(moved, origin):
    checkout, git, base, head, _ = moved
    git("remote", "set-url", "origin", origin)
    forge = Forge(base, head)
    with pytest.raises(p.Refused, match="git .*remote set-url origin") as error:
        preflight(moved, forge)
    assert "https://github.com/intigraph/yupana.git" in str(error.value)
    assert forge.alias_reads == 0
    assert git("remote", "get-url", "origin") == origin


@pytest.mark.parametrize("broken", ["missing", "malformed", "unmapped"])
def test_unavailable_or_unmapped_stack_policy_refuses(moved, broken):
    _, _, base, head, helper = moved
    if broken == "missing":
        helper.unlink()
    else:
        helper.with_suffix(".json").write_text("not-json" if broken == "malformed" else "{}")
    forge = Forge(base, head)
    with pytest.raises(p.Refused, match="remote set-url origin"):
        preflight(moved, forge)
    assert forge.alias_reads == 0


@pytest.mark.parametrize("identity", [None, {}, [], {"id": True, "full_name": CURRENT},
    {"id": 124, "full_name": CURRENT}, {"id": 123, "full_name": LEGACY},
    {"id": 123, "full_name": "foreign/yupana"}])
def test_map_alone_cannot_admit_an_unproven_redirect(moved, identity):
    _, _, base, head, _ = moved
    forge = Forge(base, head)
    forge.alias = identity
    with pytest.raises(p.Refused, match="remote set-url origin"):
        preflight(moved, forge)
    assert forge.alias_reads == 1


def test_redirect_race_refuses_dry_run_before_create(moved):
    _, _, base, head, _ = moved
    forge = Forge(base, head)

    def api(path, body=None):
        if path == f"repos/{LEGACY}" and forge.alias_reads:
            forge.alias = {"id": 124, "full_name": CURRENT}
        return forge(path, body)

    with pytest.raises(p.Refused, match="remote set-url origin"):
        p.run(moved[0], CURRENT, "main", "project-new", "Body", "Title", [],
              api=api, create=True, dry_run=True)
    assert forge.alias_reads == 2
