"""Directive crew/scheduled-jobs: no cron job files; one command declares a job in Quipu.

Each test is named for the failure it prevents. The two that must keep saying
no: a job file asking for a clock is refused (hammond's 11-13 cron file was
accepted), and `st work jobs new` never reports success for a write that did
not read back.
"""
import io
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from shantytown import cli, jobs, quipu_auth
from shantytown import quipu_jobs as q

GRAPH = "urn:example:jobs"


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
                message='make the "weekly" podcast', weekly=(1, "09:17"))
    args.update(kw)
    return q.declare_rows("podcast", **args)


def test_weekly_declaration_is_the_shape_the_reader_admits():
    decl = _weekly()
    job = decl.job
    assert isinstance(job, q.CalendarDeclaredJob)
    assert (job.weekday, job.local_time, job.timezone, job.interval_s) == (1, "09:17", "America/New_York", None)
    # The anchor is the first Tuesday 09:17 in the zone after the fixed epoch,
    # never the clock: what -n shows is byte-for-byte what is written.
    assert '"2026-01-06T09:17:00-05:00"' in decl.turtle
    assert job.target == "urn:shantytown:inbox:lex" and job.host == "urn:shantytown:host:mac"
    assert q.QUECHUA_CANONICAL + "sourceKind" in decl.turtle
    assert '\\"weekly\\"' in decl.turtle      # a quote in the message cannot break the Turtle
    # Same inputs, same revision: a reviewed dry run is what gets written.
    assert _weekly().job.revision == job.revision
    assert _weekly(message="other").job.revision != job.revision


_UCHAR_OR_ECHAR = re.compile(r'\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|(.))')


def _turtle_literal_value(turtle, predicate):
    """Decode one STRING_LITERAL_QUOTE as a Turtle parser must, refusing what
    Turtle forbids. A UCHAR naming a surrogate code point is not a character."""
    lexical = re.search(rf'<{re.escape(predicate)}> "((?:[^"\\]|\\.)*)"', turtle).group(1)

    def one(m):
        if m.group(3) is not None:
            return {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f",
                    '"': '"', "'": "'", "\\": "\\"}[m.group(3)]
        cp = int(m.group(1) or m.group(2), 16)
        assert not 0xD800 <= cp <= 0xDFFF, f"Turtle forbids surrogate UCHAR U+{cp:04X}"
        return chr(cp)
    return _UCHAR_OR_ECHAR.sub(one, lexical)


@pytest.mark.parametrize("message", [
    "weekly podcast \N{GRINNING FACE} \N{MUSICAL SCORE}",    # non-BMP: was a surrogate pair
    'caf\u00e9 "quoted" back\\slash',
    "line one\nline two\ttab\x01bell",
])
def test_a_message_round_trips_through_the_turtle_literal(message):
    decl = _weekly(message=message)
    assert _turtle_literal_value(decl.turtle, q.SCHEMA + "description") == message
    assert not re.search(r"\\u[dD][89a-fA-F]", decl.turtle)


def test_an_undecodable_message_is_refused_before_anything_is_written():
    # argv bytes that are not UTF-8 reach Python as lone surrogates
    # (surrogateescape); they have no UTF-8 form to write.
    with pytest.raises(q.JobRefused, match="undecodable"):
        _weekly(message="bad \udcff byte")


def test_the_surrogate_refusal_quotes_an_excerpt_not_the_whole_message():
    tail = "x" * 500
    with pytest.raises(q.JobRefused) as refused:
        _weekly(message="bad \udcff byte " + tail)
    assert tail not in str(refused.value)
    assert "offset 4" in str(refused.value)


def test_new_writes_a_non_bmp_message_as_valid_turtle(tmp_path, monkeypatch, capsys):
    fake = _Quipu()
    fake.pending = _weekly(message="go \N{GRINNING FACE}").body["rows"]
    monkeypatch.setenv("QUIPU_SERVER", "http://quipu.example.invalid")
    monkeypatch.setattr(quipu_auth, "write_headers", lambda server: {})
    monkeypatch.setattr(q.urllib.request, "urlopen", fake)
    assert cli.main(["--root", str(tmp_path), "work", "jobs", "--graph", GRAPH, "new", "podcast",
                     "--weekly", "tue", "09:17", "--tz", "America/New_York", "--host", "mac",
                     "--inbox", "lex", "--message", "go \N{GRINNING FACE}",
                     "--owner", "hammond"]) == cli.OK
    (written,) = fake.writes
    assert _turtle_literal_value(written, q.SCHEMA + "description") == "go \N{GRINNING FACE}"


def test_interval_declaration_uses_an_exact_duration():
    decl = q.declare_rows("tick", host="mac", owner="o", zone="UTC", inbox="lex",
                          message="x", every_s=6 * 3600 + 30)
    assert decl.job.interval_s == 21630 and '"PT6H30S"' in decl.turtle
    assert '"2026-01-05T00:00:00Z"' in decl.turtle


@pytest.mark.parametrize("start,hhmm,day,expected", [
    # 2026-03-08 02:30 does not exist in New York (spring forward).
    (datetime(2026, 3, 2, tzinfo=timezone.utc), "02:30", 6, "2026-03-15T02:30:00-04:00"),
    # 2026-11-01 01:30 happens twice in New York (fall back).
    (datetime(2026, 10, 26, tzinfo=timezone.utc), "01:30", 6, "2026-11-08T01:30:00-05:00"),
])
def test_a_weekly_slot_in_a_dst_gap_or_fold_moves_to_the_next_clean_week(monkeypatch, start, hhmm, day, expected):
    monkeypatch.setattr(q, "ANCHOR_EPOCH", start)
    decl = _weekly(weekly=(day, hhmm))
    assert f'"{expected}"' in decl.turtle      # and the reader admitted it


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
    # Quipu stores what the CLI declared. No clock is pinned: the declaration
    # is a pure function of the arguments, so these rows are what it writes.
    if not hasattr(fake, "pending"):
        fake.pending = _weekly(message="go").body["rows"]
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


def test_the_reviewed_dry_run_is_exactly_what_is_written(tmp_path, monkeypatch, capsys):
    fake = _Quipu()
    assert _new(tmp_path, monkeypatch, fake, "--dry-run") == cli.OK
    reviewed = capsys.readouterr().out
    assert _new(tmp_path, monkeypatch, fake) == cli.OK
    (written,) = fake.writes
    assert written in reviewed


def test_new_reports_unknown_not_refused_when_read_back_is_refused(tmp_path, monkeypatch, capsys):
    # The write committed, then the graph no longer decodes (a racing writer
    # left a second name for the job). "refused: nothing written" would be a lie.
    fake = _Quipu()
    rows = _weekly(message="go").body["rows"]
    clash = [dict(r, s=r["s"].replace("job:mac:podcast", "job:mac:podcast2"),
                  o=r["o"].replace("job:mac:podcast", "job:mac:podcast2") if r["objectIRI"] else r["o"])
             for r in rows]
    fake.pending = rows + clash
    assert _new(tmp_path, monkeypatch, fake) == cli.CANNOT_TELL
    captured = capsys.readouterr()
    assert "could not read it back" in captured.err and "refused" not in captured.err


def test_new_reports_unknown_when_quipu_answers_the_write_with_an_error(tmp_path, monkeypatch, capsys):
    fake = _Quipu(knot={"error": "timeout after commit"}, persist=False)
    assert _new(tmp_path, monkeypatch, fake) == cli.CANNOT_TELL
    assert "outcome unknown" in capsys.readouterr().err


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
    captured = capsys.readouterr()
    assert "podcast" in captured.out
    assert "job files not shown" in captured.err and "stale" in captured.err


def test_tend_does_not_fire_file_jobs_the_graph_read_surface_cannot_show(tmp_path, monkeypatch):
    (tmp_path / "shantytown.toml").write_text(f'[jobs]\ngraph = "{GRAPH}"\n')
    _file(tmp_path, "stale", '[trigger]\nmanual = true\n[action]\ninbox = "lex"\nmessage = "x"\n')
    monkeypatch.setattr(cli, "_jobs_runner", lambda *a, **k: pytest.fail("ran file jobs in graph mode"))
    (line,) = cli._jobs_sweep(SimpleNamespace(root=str(tmp_path)))
    assert "NOT run" in line and "stale" in line


def test_tend_still_runs_file_jobs_without_a_jobs_graph(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(cli, "_jobs_runner", lambda *a, **k: SimpleNamespace(sweep=lambda: ran.append(1) or []))
    assert cli._jobs_sweep(SimpleNamespace(root=str(tmp_path))) == [] and ran == [1]


def test_a_host_with_live_timed_files_can_keep_them_firing_while_it_migrates(tmp_path, capsys):
    # vati was not measured when the refusal shipped: migrate first, then remove.
    (tmp_path / "shantytown.toml").write_text('[jobs]\ntimed_files = "migrate"\n')
    _file(tmp_path, "podcast", '[trigger]\ncron = "17 9 * * 2"\n[action]\ninbox = "lex"\nmessage = "x"\n')
    loaded, errors = jobs.load(tmp_path)
    assert [j.trigger.kind for j in loaded] == ["cron"] and errors == []
    assert cli.main(["--root", str(tmp_path), "work", "jobs", "list"]) == cli.OK
    assert "still firing" in capsys.readouterr().err


def test_the_migration_gate_accepts_only_its_two_values(tmp_path):
    from shantytown import config
    (tmp_path / "shantytown.toml").write_text('[jobs]\ntimed_files = "yes"\n')
    with pytest.raises(config.ConfigError, match="timed_files"):
        config.load(tmp_path)


def test_a_refused_timed_file_does_not_blank_the_hosts_duty_inventory(tmp_path):
    from shantytown import duty_discovery
    _file(tmp_path, "podcast", '[trigger]\ncron = "17 9 * * 2"\n[action]\ninbox = "lex"\nmessage = "x"\n')
    _file(tmp_path, "nudge", '[trigger]\nmanual = true\n[action]\ninbox = "lex"\nmessage = "x"\n')
    duty_discovery.job_bindings(tmp_path, None)      # used to raise "source incomplete"


def test_any_other_broken_job_file_still_fails_the_duty_inventory(tmp_path):
    from shantytown import duty_discovery
    _file(tmp_path, "broken", '[trigger]\nmanual = "yes"\n[action]\ninbox = "lex"\nmessage = "x"\n')
    with pytest.raises(ValueError, match="incomplete"):
        duty_discovery.job_bindings(tmp_path, None)


def test_a_malformed_jobs_graph_setting_is_refused(tmp_path):
    from shantytown import config
    (tmp_path / "shantytown.toml").write_text('[jobs]\ngraph = "not an iri"\n')
    with pytest.raises(config.ConfigError, match="jobs.graph"):
        config.load(tmp_path)
