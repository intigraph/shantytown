"""Isolated retention demo. No installed home, credentials or processes used."""
import json
import os
from pathlib import Path
import tempfile

from shantytown.codex_retention import Refused, prune


def main():
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary) / "home"
        releases = home / "packages/standalone/releases"
        releases.mkdir(parents=True)
        for minor in range(150, 155):
            version = f"0.{minor}.0"
            path = releases / (version + "-test-target")
            (path / "bin").mkdir(parents=True)
            (path / "bin/codex").write_bytes(b"fixture payload" * 1024)
            (path / "codex").symlink_to("bin/codex")
            (path / "codex-package.json").write_text(json.dumps({
                "layoutVersion": 1, "version": version, "target": "test-target",
                "variant": "codex", "entrypoint": "bin/codex",
            }))
            for item in path.rglob("*"):
                os.utime(item, (1, 1), follow_symlinks=False)
            os.utime(path, (1, 1))
        (releases.parent / "current").symlink_to("releases/0.154.0-test-target")
        witness = home / "sessions"
        witness.mkdir()
        (witness / "record").write_bytes(b"durable evidence")
        before_witness = (witness / "record").stat().st_mtime_ns
        readers = lambda: set()  # explicit isolated custody fixture
        before = prune(home, readers=readers)
        expected = before["plan"]
        print(json.dumps({"scope": "isolated fixture", "before_releases": len(expected["releases"]),
                          "before_bytes": sum(r["bytes"] for r in expected["releases"].values()),
                          "plan_only_removed": before["removed"]}))
        live = lambda: {str(releases / expected["remove"][0] / "bin/codex")}
        try:
            prune(home, expected=expected, readers=live)
        except Refused:
            print("CONTROL: new reader makes saved plan REFUSE before deletion")
        else:
            raise AssertionError("changed reader plan was accepted")
        result = prune(home, expected=expected, readers=readers)
        after = prune(home, readers=readers)["plan"]
        assert (witness / "record").read_bytes() == b"durable evidence"
        assert (witness / "record").stat().st_mtime_ns == before_witness
        print(json.dumps({"after_releases": len(after["releases"]),
                          "after_bytes": sum(r["bytes"] for r in after["releases"].values()),
                          "removed": result["removed"], "current": after["current"],
                          "sessions_bytes_and_mtime": "unchanged"}))


if __name__ == "__main__":
    main()
