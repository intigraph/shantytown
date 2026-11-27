"""Directive crew/scheduled-jobs: no cron job files; one command declares a job in Quipu.

Each test is named for the failure it prevents. The two that must keep saying
no: a job file asking for a clock is refused (hammond's 11-13 cron file was
accepted), and `st work jobs new` never reports success for a write that did
not read back.
"""
import io
import json
from datetime import datetime, timezone

import pytest

from shantytown import cli, jobs, quipu_auth
from shantytown import quipu_jobs as q

GRAPH = "urn:example:jobs"
FIXED = datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc)


def _file(root, name, text):
    d = root / "jobs"
    d.mkdir(exist_ok=True)
    (d / f"{name}.toml").write_text(text)


@pytest.mark.parametrize("trigger", ['cron = "17 9 * * 2"', 'every = "6h"'])
def test_a_timed_job_file_is_refused_and_names_the_replacement(tmp_path, trigger):
    _file(tmp_path, "podcast", f'[trigger]\n{trigger}\n[action]\ninbox = "lex"\nmessage = "x"\n')
    loaded, errors = jobs.load(tmp_path)
    assert loaded == []
    (err,) = errors
    assert "st work jobs new" in str(err) and "Quipu" in str(err)


def test_a_timed_job_file_fails_the_list_and_warns_file_config_is_deprecated(tmp_path, capsys):
    _file(tmp_path, "podcast", '[trigger]\ncron = "17 9 * * 2"\n[action]\ninbox = "lex"\nmessage = "x"\n')
    assert cli.main(["--root", str(tmp_path), "work", "jobs", "list"]) == cli.REFUSED
    err = capsys.readouterr().err
    assert "podcast.toml: trigger.cron" in err and "DEPRECATED" in err


def test_an_event_file_job_still_loads_during_the_migration_window(tmp_path):
    _file(tmp_path, "nudge", '[trigger]\nmanual = true\n[action]\ninbox = "lex"\nmessage = "x"\n')
    loaded, errors = jobs.load(tmp_path)
    assert [j.name for j in loaded] == ["nudge"] and errors == []


def _weekly(**kw):
    args = dict(host="mac", owner="hammond", zone="America/New_York", inbox="lex",
                message='make the "weekly" podcast', weekly=(1, "09:17"),
                now=FIXED)
    args.update(kw)
    return q.declare_rows("podcast", **args)


def test_weekly_declaration_is_the_shape_the_reader_admits():
    decl = _weekly()
    job = decl.job
    assert isinstance(job, q.CalendarDeclaredJob)
    assert (job.weekday, job.local_time, job.timezone, job.interval_s) == (1, "09:17", "America/New_York", None)
    # The first slot is the NEXT Tuesday 09:17 in the zone, at that day's offset.
    assert '"2026-12-01T09:17:00-05:00"' in decl.turtle
    assert job.target == "urn:shantytown:inbox:lex" and job.host == "urn:shantytown:host:mac"
    assert q.QUECHUA_CANONICAL + "sourceKind" in decl.turtle
    assert '\\"weekly\\"' in decl.turtle      # a quote in the message cannot break the Turtle
    # Same inputs, same revision: a reviewed dry run is what gets written.
    assert _weekly().job.revision == job.revision
    assert _weekly(message="other").job.revision != job.revision


def test_interval_declaration_uses_an_exact_duration():
    decl = q.declare_rows("tick", host="mac", owner="o", zone="UTC", inbox="lex",
                          message="x", every_s=6 * 3600 + 30)
    assert decl.job.interval_s == 21630 and '"PT6H30S"' in decl.turtle


@pytest.mark.parametrize("kw,needle", [
    (dict(weekly=(1, "9:17")), "HH:MM"),
    (dict(weekly=(1, "24:00")), "HH:MM"),
    (dict(weekly=None), "exactly one"),
    (dict(every_s=3600), "exactly one"),
    (dict(weekly=None, every_s=30), "sixty"),
    (dict(zone="Mars/Olympus"), "timezone"),
    (dict(inbox="lex; rm -rf"), "agent"),
    (dict(message="  "), "message"),
    (dict(owner=""), "owner"),
    (dict(host="not an iri"), "host"),
])
def test_bad_declarations_refuse_before_anything_is_written(kw, needle):
    with pytest.raises(q.JobRefused, match=needle):
        _weekly(**kw)


def test_weekday_names_are_strict():
    assert q.parse_weekday("Tue") == 1 and q.parse_weekday("sunday") == 6
    with pytest.raises(q.JobRefused):
        q.parse_weekday("tues")


class _Quipu:
    """A fake Quipu: /query answers the graph's rows, /knot appends them."""

    def __init__(self, rows=(), knot=None, persist=True):
        self.rows, self.knot, self.persist, self.writes = list(rows), knot, persist, []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data)
        assert body["graph"] == GRAPH
        if req.full_url.endswith("/knot"):
            self.writes.append(body["turtle"])
            if self.persist:
                self.rows.extend(self.pending)
            out = self.knot or {"ok": True}
        else:
            out = dict(count=len(self.rows), rows=self.rows, truncated=False)
        return io.BytesIO(json.dumps(out).encode())


def _new(tmp_path, monkeypatch, fake, *extra):
    monkeypatch.setenv("QUIPU_SERVER", "http://quipu.example.invalid")
    monkeypatch.setattr(quipu_auth, "write_headers", lambda server: {})
    monkeypatch.setattr(q.urllib.request, "urlopen", fake)
    # Quipu stores what the CLI declared; the clock is pinned so the expected
    # rows (and so the revision read back) are computable here.
    fake.pending = _weekly(message="go").body["rows"]
    real = q.declare_rows
    monkeypatch.setattr(q, "declare_rows", lambda *a, **k: real(*a, **{**k, "now": FIXED}))
    return cli.main(["--root", str(tmp_path), "work", "jobs", "--graph", GRAPH, "new", "podcast",
                     "--weekly", "tue", "09:17", "--tz", "America/New_York", "--host", "mac",
                     "--inbox", "lex", "--message", "go", "--owner", "hammond", *extra])


def test_new_writes_once_and_succeeds_only_after_read_back(tmp_path, monkeypatch, capsys):
    fake = _Quipu()
    assert _new(tmp_path, monkeypatch, fake) == cli.OK
    assert len(fake.writes) == 1
    out = capsys.readouterr().out
    assert "<urn:shantytown:job:mac:podcast>" in out and "declared and read back" in out


def test_new_dry_run_prints_the_declaration_and_writes_nothing(tmp_path, monkeypatch, capsys):
    fake = _Quipu()
    assert _new(tmp_path, monkeypatch, fake, "--dry-run") == cli.OK
    assert fake.writes == [] and "dry run: nothing written" in capsys.readouterr().out


def test_new_reports_unknown_when_the_write_does_not_read_back(tmp_path, monkeypatch, capsys):
    fake = _Quipu(persist=False)
    assert _new(tmp_path, monkeypatch, fake) == cli.CANNOT_TELL
    captured = capsys.readouterr()
    assert "cannot tell" in captured.err and "declared and read back" not in captured.out


def test_new_reports_unknown_when_a_different_revision_reads_back(tmp_path, monkeypatch, capsys):
    fake = _Quipu()
    fake.pending = _weekly(message="someone else's").body["rows"]   # a racing writer
    monkeypatch.setenv("QUIPU_SERVER", "http://quipu.example.invalid")
    monkeypatch.setattr(quipu_auth, "write_headers", lambda server: {})
    monkeypatch.setattr(q.urllib.request, "urlopen", fake)
    with pytest.raises(q.JobsUnavailable, match="did not read back"):
        q.JobCatalogue(GRAPH, root=tmp_path).declare(_weekly(message="go"))


def test_new_surfaces_a_shacl_refusal_with_no_error_key(tmp_path, monkeypatch, capsys):
    fake = _Quipu(knot={"conforms": False, "issues": [{"path": "p", "message": "bad"}]}, persist=False)
    assert _new(tmp_path, monkeypatch, fake) == cli.REFUSED
    assert "SHACL" in capsys.readouterr().err


def test_new_never_replaces_an_existing_job(tmp_path, monkeypatch, capsys):
    fake = _Quipu(rows=_weekly(message="older").body["rows"])
    assert _new(tmp_path, monkeypatch, fake) == cli.REFUSED
    assert fake.writes == [] and "already declared" in capsys.readouterr().err


def test_new_without_a_jobs_graph_refuses(tmp_path, capsys):
    assert cli.main(["--root", str(tmp_path), "work", "jobs", "new", "podcast", "--weekly", "tue",
                     "09:17", "--host", "mac", "--inbox", "lex", "--message", "go",
                     "--owner", "o"]) == cli.REFUSED
    assert "[jobs] graph" in capsys.readouterr().err


def test_a_configured_jobs_graph_is_the_read_surface_with_no_toml(tmp_path, monkeypatch, capsys):
    (tmp_path / "shantytown.toml").write_text(f'[jobs]\ngraph = "{GRAPH}"\n')
    _file(tmp_path, "stale", '[trigger]\nmanual = true\n[action]\ninbox = "lex"\nmessage = "x"\n')
    monkeypatch.setattr(jobs, "load", lambda *a: pytest.fail("read job TOML with a jobs graph set"))
    monkeypatch.setenv("QUIPU_SERVER", "http://quipu.example.invalid")
    monkeypatch.setattr(q.urllib.request, "urlopen", _Quipu(rows=_weekly().body["rows"]))
    assert cli.main(["--root", str(tmp_path), "work", "jobs", "list"]) == cli.OK
    assert "podcast" in capsys.readouterr().out


def test_a_malformed_jobs_graph_setting_is_refused(tmp_path):
    from shantytown import config
    (tmp_path / "shantytown.toml").write_text('[jobs]\ngraph = "not an iri"\n')
    with pytest.raises(config.ConfigError, match="jobs.graph"):
        config.load(tmp_path)
