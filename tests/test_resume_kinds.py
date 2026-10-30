"""`release:` and `installed:` resume kinds (aegis-tdf part 2).

Before these, the only machine-testable kinds were `closed:`, `date:` and per-item
`event:` bindings, and the registry held one disabled binding. So "resume when the
next release ships" or "when the new version is installed" had no mechanism, and
`st work defer` refused it (measured on aegis-tri, 2026-10-21).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from shantytown import deferrals, resume_kinds
from shantytown.dispatch import DeferRefused, Dispatcher
from shantytown.files import FilesRegistry, FilesTracker
from shantytown.tmux import NullPanes

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


def done(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


# --- release: ---------------------------------------------------------------------

def test_a_published_release_is_met():
    body = json.dumps({"tag_name": "v0.15.0", "draft": False, "published_at": "2026-10-21T05:19:26Z"})
    met, why = resume_kinds.release("scbrown/yupana@v0.15.0", run=lambda argv: done(out=body))
    assert met is True and "published" in why


def test_a_draft_release_is_not_met():
    body = json.dumps({"tag_name": "v0.15.0", "draft": True, "published_at": None})
    met, _ = resume_kinds.release("scbrown/yupana@v0.15.0", run=lambda argv: done(out=body))
    assert met is False


def test_a_missing_release_is_not_met_but_other_failures_are_unknown():
    missing = resume_kinds.release("scbrown/yupana@v9.9.9",
                                   run=lambda argv: done(1, err="gh: Not Found (HTTP 404)"))
    assert missing[0] is False
    flaky = resume_kinds.release("scbrown/yupana@v0.15.0",
                                 run=lambda argv: done(1, err="HTTP 502 Bad Gateway"))
    assert flaky[0] is None, "a failed read must keep the hold, never release it"
    wrong = resume_kinds.release("scbrown/yupana@v0.15.0",
                                 run=lambda argv: done(out=json.dumps({"tag_name": "v0.14.0"})))
    assert wrong[0] is None


def test_release_reads_only_the_validated_repository_and_tag():
    seen = []
    resume_kinds.release("scbrown/yupana@v0.15.0",
                         run=lambda argv: seen.append(argv) or done(1, err="HTTP 404"))
    assert seen == [["gh", "api", "repos/scbrown/yupana/releases/tags/v0.15.0"]]
    for bad in ("yupana@v1", "scbrown/yupana", "scbrown/yu pana@v1", "a/b@$(x)", "../../x/y@v1"):
        with pytest.raises(ValueError):
            resume_kinds.validate("release", bad)


# --- installed: -------------------------------------------------------------------

def version(text):
    return lambda argv: done(out=text)


@pytest.mark.parametrize("arg,have,expect", [
    ("yupana@0.15.0", "yupana 0.15.0", True),
    ("yupana@0.15.0", "yupana 0.14.9", False),
    ("yupana>=0.15", "yupana 0.15.2", True),
    ("yupana>0.15.0", "yupana 0.15.0", False),
    ("yupana>0.15.0", "yupana 0.15.1", True),
    ("sd==0.6.1", "sd 0.6.1 (seeds)", True),
    ("sd==0.6.1", "sd 0.6.2 (seeds)", False),
    # grant review of ee38395: a `v` prefix once read as 14.0 and released early,
    # a pre-release once equalled its release, and a major-only want raised TypeError.
    ("quipu@0.15", "quipu v0.14.0", False),
    ("quipu@0.15", "quipu v0.15.0", True),
    ("quipu@0.15.0", "quipu 0.15.0-rc.1", False),
    ("quipu==0.15.0", "quipu 0.15.0-rc.1", False),
    ("quipu>=0.14.9", "quipu 0.15.0-rc.1", True),
    ("sd@1", "sd 0.9.9", False),
    ("sd@1", "sd 1.0.0", True),
    ("st@0.7", "st 0.7.1 (a62f35d-dirty)", True),
])
def test_installed_compares_the_tools_own_version(arg, have, expect):
    met, _ = resume_kinds.installed(arg, run=version(have), which=lambda t: f"/bin/{t}")
    assert met is expect


def test_installed_runs_only_the_allowlisted_tool_with_a_fixed_argv():
    seen = []
    resume_kinds.installed("bobbin>=0.16", run=lambda argv: seen.append(argv) or done(out="bobbin 0.16.3"),
                           which=lambda t: f"/opt/{t}")
    assert seen == [["/opt/bobbin", "--version"]]
    for bad in ("rm@1.0", "yupana", "yupana@", "yupana<0.15", "yupana@0.15;id", "yupana@1.2.3.4"):
        with pytest.raises(ValueError):
            resume_kinds.validate("installed", bad)


def test_installed_is_unknown_when_it_cannot_tell():
    assert resume_kinds.installed("yupana@0.15", run=version("x"), which=lambda t: None)[0] is None
    assert resume_kinds.installed("yupana@0.15", run=version("no digits"),
                                  which=lambda t: "/bin/yupana")[0] is None
    assert resume_kinds.installed("yupana@0.15", run=lambda argv: done(2, out="yupana 9.9.9"),
                                  which=lambda t: "/bin/yupana")[0] is None


def test_evaluate_answers_every_validated_installed_condition():
    """Whatever `validate` accepts, `evaluate` answers instead of raising."""
    for arg in ("sd@1", "sd>=1.2", "sd==0.6.1", "sd>0"):
        met, _ = resume_kinds.evaluate("installed", arg, run=version("sd 0.6.1"), which=lambda t: "/bin/sd")
        assert met in (True, False)


# --- the sweeper and the writer --------------------------------------------------

def row(marker):
    return {"id": "aegis-x", "status": "deferred", "notes": f"resume_when: {marker}", "labels": []}


def test_the_sweeper_releases_on_met_and_holds_on_unknown(monkeypatch):
    answers = {"release": (True, "published"), "installed": (None, "not on PATH")}
    monkeypatch.setattr(resume_kinds, "evaluate", lambda kind, arg: answers[kind])
    met_row, unknown_row = row("release:scbrown/yupana@v0.15.0"), row("installed:yupana>0.15.0")
    by_id = {}
    for r in (met_row, unknown_row):
        [finding] = deferrals.evaluate([r], NOW)
        by_id[r["notes"]] = finding
    met = by_id[met_row["notes"]]
    assert met.met and deferrals.can_release(met_row, met, NOW)
    unknown = by_id[unknown_row["notes"]]
    assert not unknown.met and unknown.untestable and not deferrals.can_release(unknown_row, unknown, NOW)


@pytest.fixture
def world(tmp_path: Path):
    tracker = FilesTracker(tmp_path / "items")
    tracker.update("item-1", title="waits for a release", status="open", assignee="ian")
    tracker.update("item-1", priority=2)
    return Dispatcher(FilesRegistry(tmp_path / "crew"), tracker, NullPanes()), tracker


def test_defer_accepts_a_release_condition(world):
    d, tracker = world
    r = d.defer("item-1", "external", "resume_when: release:scbrown/yupana@v0.16.0")
    assert r.condition.endswith("release:scbrown/yupana@v0.16.0")
    assert "resume_when: release:scbrown/yupana@v0.16.0" in tracker.get("item-1").notes


def test_defer_refuses_a_malformed_version_condition_without_writing(world):
    d, tracker = world
    before = tracker._path("item-1").read_bytes()
    with pytest.raises(DeferRefused, match="installed:<tool>"):
        d.defer("item-1", "external", "resume_when: installed:rm@1.0")
    assert tracker._path("item-1").read_bytes() == before

# Forge identity is pinned in the condition, never selected as an arbitrary URL.
FORGE_ARG = 'forgejo:forge.example/team/project@v1.2.3'
FORGE_ENV = {'SHANTY_FORGEJO_URL': 'https://forge.example'}


def forge_read(data, env=None, url=None):
    from io import BytesIO
    class Reply(BytesIO):
        def geturl(self):
            return url or 'https://forge.example/api/v1/repos/team/project/releases/tags/v1.2.3'
    class Reader:
        def open(self, request, timeout):
            assert request.full_url == 'https://forge.example/api/v1/repos/team/project/releases/tags/v1.2.3'
            assert timeout == resume_kinds.TIMEOUT
            return Reply(json.dumps(data).encode())
    return resume_kinds.forgejo_release(FORGE_ARG, env=FORGE_ENV if env is None else env, opener=Reader())


def publication():
    return {'tag_name': 'v1.2.3', 'draft': False,
            'html_url': 'https://forge.example/team/project/releases/tag/v1.2.3',
            'published_at': '2026-10-29T12:00:00Z'}


def test_forgejo_published_and_draft_are_distinct():
    assert forge_read(publication())[0] is True
    body = publication(); body['draft'] = True
    assert forge_read(body)[0] is False


@pytest.mark.parametrize('field,value', [
    ('tag_name', 'v9'), ('draft', None), ('draft', 'false'),
    ('html_url', 'https://other.example/team/project/releases/tag/v1.2.3'),
    ('html_url', 'https://forge.example/other/project/releases/tag/v1.2.3'),
    ('published_at', None), ('published_at', 'yesterday'),
    ('published_at', '2026-10-29T12:00:00'),
])
def test_forgejo_partial_or_wrong_scope_keeps_hold(field, value):
    body = publication(); body[field] = value
    assert forge_read(body)[0] is None


@pytest.mark.parametrize('base', ['', 'https://other.example', 'https://user:secret@forge.example',
                                 'https://forge.example/path', 'https://forge.example?x=1',
                                 'https://forge.example:0'])
def test_forgejo_wrong_config_never_reads(base):
    assert forge_read(publication(), {'SHANTY_FORGEJO_URL': base})[0] is None


def test_forgejo_redirect_response_cannot_satisfy():
    assert forge_read(publication(), url='https://other.example/')[0] is None


def test_forgejo_condition_is_accepted_by_normal_writer(world):
    d, tracker = world
    d.defer('item-1', 'external', 'resume_when: release:' + FORGE_ARG)
    assert ('resume_when: release:' + FORGE_ARG) in tracker.get('item-1').notes


@pytest.mark.parametrize('arg', ['forgejo:https://forge.example/a/b@v1',
                                'forgejo:forge.example/../b@v1',
                                'forgejo:forge.example/a/b@$(x)'])
def test_forgejo_malformed_condition_refuses(arg):
    with pytest.raises(ValueError):
        resume_kinds.validate('release', arg)


@pytest.mark.parametrize('failure', [OSError('offline'), ValueError('invalid JSON')])
def test_forgejo_read_failures_remain_unknown(failure):
    class Reader:
        def open(self, request, timeout):
            raise failure
    assert resume_kinds.forgejo_release(FORGE_ARG, env=FORGE_ENV, opener=Reader())[0] is None


def test_forgejo_real_transport_refuses_redirect_and_bounds_body(monkeypatch):
    from io import BytesIO
    captured = []
    class Reply(BytesIO):
        def geturl(self):
            return 'https://forge.example/api/v1/repos/team/project/releases/tags/v1.2.3'
    class Reader:
        def open(self, request, timeout):
            assert request.get_header('Authorization') == 'token fixture-token'
            return Reply(b'x' * 262145)
    def build(handler):
        assert handler.redirect_request(None, None, None, None, None, None) is None
        captured.append(True)
        return Reader()
    monkeypatch.setattr(resume_kinds.urllib.request, 'build_opener', build)
    monkeypatch.setenv('SHANTY_FORGEJO_URL', 'https://forge.example')
    monkeypatch.setenv('SHANTY_FORGEJO_TOKEN', 'fixture-token')
    assert resume_kinds.evaluate('release', FORGE_ARG)[0] is None
    assert captured == [True]


def test_forgejo_sweeper_uses_fact_condition_and_retains_unknown(monkeypatch):
    monkeypatch.setattr(resume_kinds, 'forgejo_release', lambda arg: (None, 'scope UNKNOWN'))
    finding = deferrals.evaluate([row('release:' + FORGE_ARG)], now=NOW)[0]
    assert not finding.met and finding.untestable
    assert not deferrals.can_release(row('release:' + FORGE_ARG), finding, NOW)
