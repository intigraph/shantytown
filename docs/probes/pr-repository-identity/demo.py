#!/usr/bin/env python3
"""Run private forge fixtures against two adapter revisions; no network writes."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import pr_preflight as candidate


def measure(module, directory):
    head, base = "a" * 40, "b" * 40
    module.candidate = lambda *a: {
        "head": head, "head_ref": "feature", "base": base,
        "base_ref": "main", "files": ["file.py"],
    }
    body = directory / "body.md"
    body.write_text("Private fixture; no external PR is created.")
    results = []
    for case in ("canonical", "renamed", "null_post", "lost_post", "missing_identity"):
        writes = []
        repo = "example/previous" if case == "renamed" else "example/current"

        def api(path, payload=None):
            if payload is None:
                if path == f"repos/{repo}":
                    return None if case == "missing_identity" else {
                        "id": 123, "full_name": "example/current",
                    }
                if "/pulls?" in path:
                    return []
                raise AssertionError(path)
            writes.append(payload)
            if case == "lost_post":
                raise module.Refused("lost response")
            if case == "null_post":
                return None
            return {"number": 99, "html_url": "https://github.com/example/current/pull/99",
                    "head": {"sha": head}, "base": {"sha": base}}

        module.github = api
        args = SimpleNamespace(
            body_file=body, dispositions_file=None, checkout="private-fixture",
            repository=repo, base="main", bead="project-task", title="Private probe",
            bead_family=[], create=True, draft=False, dry_run=False,
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = module.command(args)
        response = json.loads(stdout.getvalue())
        results.append({"case": case, "exit": rc, "post_attempts": len(writes),
                        "response": response, "stderr": stderr.getvalue().strip()})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = subprocess.check_output(
        ["git", "show", f"{args.baseline_ref}:shantytown/pr_preflight.py"], cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="pr-identity-") as temp:
        directory = Path(temp)
        old = directory / "before.py"
        old.write_bytes(source)
        spec = importlib.util.spec_from_file_location("shantytown._identity_before", old)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        before = measure(baseline, directory)
        after = measure(candidate, directory)
    assert before[1]["post_attempts"] == 1 and after[1]["post_attempts"] == 0
    assert after[1]["exit"] == 2 and after[1]["response"]["created"] is False
    assert after[0]["exit"] == 0 and after[0]["post_attempts"] == 1
    for index in (2, 3):
        assert after[index]["exit"] == 2 and after[index]["post_attempts"] == 1
        assert after[index]["response"]["outcome"] == "indeterminate"
    assert after[4]["exit"] == 2 and after[4]["post_attempts"] == 0
    result = {"baseline_ref": args.baseline_ref,
              "baseline_source_sha256": hashlib.sha256(source).hexdigest(),
              "candidate_source_sha256": hashlib.sha256(
                  (ROOT / "shantytown/pr_preflight.py").read_bytes()).hexdigest(),
              "before": before, "after": after}
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Private candidate/forge fixtures; no installed command or network mutation.")
    for previous, current in zip(before, after):
        print(f"{current['case']}: POSTs {previous['post_attempts']} -> "
              f"{current['post_attempts']}; exit {previous['exit']} -> {current['exit']}")
        if current["stderr"]:
            print(current["stderr"])


if __name__ == "__main__":
    main()
