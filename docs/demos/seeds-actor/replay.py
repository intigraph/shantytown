"""Restore the exact text-encoded terminal recording and replay it privately."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parent
    recording = json.loads((root / "output.json").read_text())
    assert recording["format"] == "script-output-lines-v1"
    raw = "".join(recording["lines"]).encode()
    assert hashlib.sha256(raw).hexdigest() == recording["sha256"]
    with tempfile.TemporaryDirectory(prefix="actor-replay-") as directory:
        log = Path(directory) / "output.log"
        log.write_bytes(raw)
        return subprocess.run(["scriptreplay", "--log-out", str(log),
                               "--log-timing", str(root / "timing.log")]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
