"""Offline native capture results; only subprocess.run is mocked."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch


def probe():
    from shantytown import input_observation, tmux, triage

    panes = tmux.Tmux(socket="offline-fixture")
    rows = []
    for rc in (0, 1):
        completed = subprocess.CompletedProcess(
            ["offline-fixture"], rc, stdout="", stderr="private adapter detail")
        with patch.object(tmux.subprocess, "run", return_value=completed) as run:
            result = input_observation.capture(
                panes, "offline-pane", wall_clock=lambda: 1000, monotonic=lambda: 2)
            assert run.call_count == 1 and run.call_args.kwargs["timeout"] == 5
        assert "private" not in json.dumps(result) and "offline-pane" not in json.dumps(result)
        rows.append({key: result[key] for key in ("state", "reason", "busy")})
        print(f"Native capture rc={rc}:", json.dumps(rows[-1]), flush=True)

    with patch.object(tmux.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired("private adapter detail", 5)):
        result = input_observation.capture(panes, "offline-pane")
    print("Timeout:", json.dumps({key: result[key] for key in ("state", "reason", "busy")}))
    assert result["state"] == triage.INPUT_UNKNOWN and result["reason"] == "capture-timeout"
    assert "private" not in json.dumps(result)
    assert rows[0] == dict(state=triage.INPUT_ABSENT, reason="no-composer-frame", busy=False)
    if rows[1] != dict(state=triage.INPUT_UNKNOWN, reason="capture-failed", busy=None):
        print("FAIL: native capture exit was lost; failure is not a successful no-frame observation.")
        return 1
    print("PASS: native failure stays UNKNOWN; successful no-frame and timeout remain distinct.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path,
                        help="isolated shantytown package from reviewed 816a8ae")
    parser.add_argument("--probe-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.baseline_dir:
        print("BEFORE: reviewed 816a8ae native adapter, same subprocess result probe.", flush=True)
        env = dict(os.environ, PYTHONPATH=str(args.baseline_dir.resolve()))
        before = subprocess.run([sys.executable, __file__, "--probe-only"], env=env,
                                capture_output=True, text=True)
        print(before.stdout, end="", flush=True)
        if before.returncode != 1 or "FAIL: native capture exit was lost" not in before.stdout:
            print(before.stderr, end="")
            raise SystemExit("Baseline did not reproduce the required behavior failure.")
    if not args.probe_only:
        print("AFTER: checked capture opts in; no live terminal, sends, clears or lifecycle action.",
              flush=True)
    return probe()


if __name__ == "__main__":
    raise SystemExit(main())
