"""A parseable PR title and visible sections are separate release-note gates."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/check-pr-title.py'
spec = importlib.util.spec_from_file_location('pr_title', SCRIPT)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


@pytest.mark.parametrize('kind', policy.TYPES)
def test_supported_types_are_valid_and_visible(kind):
    assert policy.valid(f'{kind}: a change')
    assert policy.valid(f'{kind}(inbox)!: a breaking change')
    sections = json.loads((ROOT / 'release-please-config.json').read_text())['packages']['.']['changelog-sections']
    assert any(row['type'] == kind and row['hidden'] is False for row in sections)


@pytest.mark.parametrize('title', [
    'Enforce ten-item local assignment cap', 'Fix: uppercase', 'unknown: a change',
    'fix:', 'fix: ', 'fix:  summary', 'fix(): summary', 'fix( ): summary',
    'fix(inbox\n): summary', 'fix: summary\nsecond line', None, 123,
])
def test_refuses_unparseable_titles(title):
    assert not policy.valid(title)


@pytest.mark.parametrize('title', [
    'fix: a change (aegis-abc123)', 'feat!: a change [hq-abc123.2.10]',
    'docs: qp-abcdefghij', 'fix(scope): gassy-abc123',
])
def test_tracker_titles_are_refused_without_rewrite(title):
    assert not policy.valid(title)


def test_public_refs_and_near_matches_are_preserved():
    assert policy.valid('fix: keep #42 and model-v2 and not-aegis-abc123')


@pytest.mark.parametrize('payload,accepted', [
    ({'pull_request': {'title': 'fix: a change'}}, True),
    ({'pull_request': {'title': 'Unparseable title'}}, False),
    ({'pull_request': {'title': 'fix: a change [aegis-abc123]'}}, False),
    ({'pull_request': {}}, False), ({}, False), ([], False),
])
def test_actual_event_cli(tmp_path, monkeypatch, payload, accepted):
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(payload))
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'pull_request')
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event))
    run = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert (run.returncode == 0) is accepted
    assert 'Traceback' not in run.stderr


def test_push_does_not_require_pr_payload(monkeypatch):
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'push')
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)
    assert subprocess.run([sys.executable, str(SCRIPT)], capture_output=True).returncode == 0


def test_title_edit_rechecks_already_required_jobs():
    workflow = (ROOT / '.github/workflows/ci.yml').read_text()
    assert 'types: [opened, synchronize, reopened, edited, ready_for_review]' in workflow
    test_job = workflow.split('  test:', 1)[1].split('\n  order-independence:', 1)[0]
    assert 'python scripts/check-pr-title.py' in test_job
