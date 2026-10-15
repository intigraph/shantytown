"""Execute the publication and identity gates without a release API writer."""
import os
from pathlib import Path
import subprocess
import shutil
import sys

import pytest


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/release.yml"


def step_script(name):
    """Read a literal shell block without adding a YAML runtime dependency."""
    lines = WORKFLOW.read_text().splitlines()
    start = lines.index(f"      - name: {name}")
    run = next(i for i in range(start + 1, len(lines)) if lines[i] == "        run: |")
    block = []
    for line in lines[run + 1:]:
        if line and not line.startswith("          "):
            break
        block.append(line[10:] if line else "")
    return "\n".join(block) + "\n"


@pytest.mark.parametrize("draft,expected", [("true", 0), ("false", 1), ("UNKNOWN", 1)])
def test_automated_publication_requires_confirmed_draft(tmp_path, draft, expected):
    fixture = tmp_path / "bin"
    fixture.mkdir()
    gh = fixture / "gh"
    gh.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                  'if [[ "$1 $2" == "release view" ]]; then\n'
                  ' [[ "$DRAFT" == UNKNOWN ]] && exit 1\n'
                  ' echo "$DRAFT"\nfi\n')
    gh.chmod(0o755)
    env = dict(os.environ, PATH=f"{fixture}:{os.environ['PATH']}",
               CALL_LOG=str(tmp_path / "calls"), DRAFT=draft,
               GITHUB_REF="refs/heads/main", RELEASE_TAG="v0.4.1",
               GITHUB_REPOSITORY="example/project")
    result = subprocess.run(["bash", "-euo", "pipefail", "-c",
                             step_script("Publish the release")], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode == expected
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls[0].startswith("release view v0.4.1 ")
    if draft == "true":
        assert calls[1].startswith("release upload v0.4.1 ")
        assert calls[2].endswith("--draft=false")
    else:
        assert len(calls) == 1


@pytest.mark.parametrize("tag,sha,ok", [("v0.4.1", "HEAD", True),
                                        ("v0.4.2", "HEAD", False),
                                        ("v0.4.1", "wrong-sha", False)])
def test_tag_and_trigger_identity_gate(tmp_path, tag, sha, ok):
    fixture = tmp_path / "bin"
    fixture.mkdir()
    shutil.copy2(sys.executable, fixture / "python")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.4.1"\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
    head = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    result = subprocess.run(["bash", "-euo", "pipefail", "-c",
                             step_script("Tag matches the declared version")],
                            cwd=tmp_path, env=dict(os.environ, PATH=f"{fixture}:{os.environ['PATH']}", RELEASE_TAG=tag,
                            GITHUB_SHA=head if sha == "HEAD" else sha), capture_output=True)
    assert (result.returncode == 0) == ok


def job_block(name):
    """One top-level job's literal lines, ending at the next job key."""
    lines = WORKFLOW.read_text().splitlines()
    start = lines.index(f"  {name}:")
    block = []
    for line in lines[start + 1:]:
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            break
        block.append(line)
    return "\n".join(block)


def test_pypi_upload_waits_for_the_registered_publisher():
    upload, notice = job_block("pypi"), job_block("pypi-not-registered")
    assert "vars.PYPI_PUBLISHER_REGISTERED == 'true'" in upload
    assert "vars.PYPI_PUBLISHER_REGISTERED != 'true'" in notice
    # Both arms keep the same release/backfill success gate, so exactly one runs.
    gate = "(needs.release.result == 'success' || needs.pypi-backfill.result == 'success')"
    assert gate in upload and gate in notice
    # Only the upload job may mint an OIDC token; the notice job has no permissions.
    assert WORKFLOW.read_text().count("id-token: write") == 1 and "id-token: write" in upload
    assert "permissions: {}" in notice and "environment:" not in notice


def test_unregistered_publisher_skip_is_a_visible_notice():
    result = subprocess.run(["bash", "-c", step_script("Skip PyPI until the Trusted Publisher is registered")],
                            capture_output=True, text=True, check=True)
    assert result.stdout.startswith("::notice title=PyPI upload skipped::")
