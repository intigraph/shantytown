"""Every ephemeral job is one Shuttle run behind a signer interface (aegis-za4f.19.1).

Three claims, each shown able to say no: a run starts, advances and ends;
illegal transitions are refused before any signer is asked; and the current
signer's transitions verify — with a tampered signature shown failing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from shantytown import ephemeral as eph
from shantytown import job_runs as jr


class FakeSigner:
    """The Signer surface with no keys at all — what the S2 broker will be."""

    def __init__(self, identity="sattler", refuse=()):
        self.identity = identity
        self.calls = []
        self.refuse = set(refuse)

    def define(self, defn):
        self.calls.append(("define", defn["name"]))

    def start(self, defn, run):
        self.calls.append(("start", defn["name"], run))
        if "start" in self.refuse:
            raise jr.RunRefused("broker down")

    def advance(self, run, step):
        self.calls.append(("advance", run, step))
        if step in self.refuse:
            raise jr.RunRefused(f"signer refused {step}")

    def verify(self, run):
        return "all verify"


def _rec(job="task", name="eph-task-abc123"):
    return {"name": name, "job": job, "administrator": "sattler", "item": "x-1"}


# --- start / advance / end ----------------------------------------------------

def test_task_run_starts_advances_and_ends_reported():
    s, rec = FakeSigner(), _rec()
    rec["shuttle_run"] = jr.begin(rec, s)
    assert rec["shuttle_run"]["state"] == "spawned"
    jr.step(rec, "claim", s)
    entry = jr.end(rec, "done", s)
    assert entry["state"] == "reported"
    assert entry["steps"] == ["claim", "work", "report"]
    assert s.calls == [("start", "st-ephemeral-task-v1", "eph-task-abc123"),
                       ("advance", "eph-task-abc123", "claim"),
                       ("advance", "eph-task-abc123", "work"),
                       ("advance", "eph-task-abc123", "report")]


@pytest.mark.parametrize("verdict,steps,final", [
    ("approve", ["claim", "approve", "report"], "reported"),
    ("request-changes", ["claim", "request-changes"], "changes-requested"),
    ("failed", ["claim", "fail"], "failed"),
])
def test_review_run_ends_on_its_verdict(verdict, steps, final):
    s, rec = FakeSigner(), _rec("review", "eph-review-abc123")
    rec["shuttle_run"] = jr.begin(rec, s)
    assert rec["shuttle_run"]["definition"] == "st-ephemeral-review-v1"
    jr.step(rec, "claim", s)
    entry = jr.end(rec, verdict, s)
    assert (entry["steps"], entry["state"]) == (steps, final)


def test_a_job_that_never_claimed_ends_failed_not_reported():
    # A launch that was refused never delivered the job: it earned no success path.
    s, rec = FakeSigner(), _rec()
    rec["shuttle_run"] = jr.begin(rec, s)
    assert jr.end(rec, "done", s)["state"] == "failed"


def test_ending_twice_is_a_no_op():
    s, rec = FakeSigner(), _rec()
    rec["shuttle_run"] = jr.begin(rec, s)
    jr.step(rec, "claim", s)
    jr.end(rec, "done", s)
    n = len(s.calls)
    assert jr.end(rec, "failed", s)["state"] == "reported"
    assert len(s.calls) == n


# --- illegal transitions ------------------------------------------------------

@pytest.mark.parametrize("job,state,step", [
    ("task", "spawned", "report"),        # skipping the claim
    ("task", "reported", "fail"),         # leaving a terminal
    ("review", "claimed", "enqueue"),     # enqueue without approval
    ("review", "claimed", "open-pr"),     # a step of another workflow
])
def test_illegal_transition_is_refused_before_the_signer(job, state, step):
    s, rec = FakeSigner(), _rec(job)
    rec["shuttle_run"] = dict(jr.begin(rec, s), state=state)
    s.calls.clear()
    with pytest.raises(jr.RunRefused):
        jr.step(rec, step, s)
    assert s.calls == []
    assert rec["shuttle_run"]["state"] == state


def test_legal_transition_is_accepted_the_control_for_the_refusals():
    s, rec = FakeSigner(), _rec("review")
    rec["shuttle_run"] = dict(jr.begin(rec, s), state="approved")
    assert jr.step(rec, "enqueue", s)["state"] == "enqueued"


def test_signer_refusal_is_recorded_and_the_state_does_not_move():
    s, rec = FakeSigner(refuse={"work"}), _rec()
    rec["shuttle_run"] = jr.begin(rec, s)
    jr.step(rec, "claim", s)
    entry = jr.end(rec, "done", s)             # never raises: the job must end
    assert entry["state"] == "claimed"
    assert "work refused" in entry["error"]


def test_no_signer_says_so_instead_of_inventing_a_run():
    entry = jr.begin(_rec(), None)
    assert entry["state"] is None and "no signer" in entry["error"]
    with pytest.raises(jr.RunRefused):
        jr.step(dict(_rec(), shuttle_run=entry), "claim", None)


def test_run_off_is_the_negative_control(monkeypatch):
    monkeypatch.setenv("SHANTY_JOB_RUNS", "none")
    assert jr.signer_for(_rec()) is None


# --- the registered-key signer: argv, no keys anywhere ------------------------

class Recorder:
    def __init__(self, results=()):
        self.argv, self.results = [], list(results)

    def __call__(self, argv, **kw):
        assert "env" not in kw                # inherits; adds no key variable
        self.argv.append(argv)
        rc, err = self.results.pop(0) if self.results else (0, "")
        return subprocess.CompletedProcess(argv, rc, "", err)


def test_registered_key_signer_never_generates_or_passes_a_key():
    run = Recorder()
    s = jr.RegisteredKeySigner(identity="sattler", binary="shuttle", run=run)
    s.start(jr.TASK, "eph-task-abc123")
    s.advance("eph-task-abc123", "claim")
    for argv in run.argv:
        assert argv[:2] == ["shuttle", "--require-existing-keys"]
        assert not any("pk8" in a or "KEY" in a for a in argv)
        assert argv[argv.index("--agent") + 1] == "sattler"   # never an eph-* identity


def test_registered_key_signer_defines_once_on_an_unknown_workflow():
    run = Recorder([(1, "shuttle: unknown workflow 'st-ephemeral-task-v1'"), (0, ""), (0, "")])
    jr.RegisteredKeySigner(identity="sattler", run=run).start(jr.TASK, "eph-task-abc123")
    assert [a[2] for a in run.argv] == ["start", "define", "start"]


def test_registered_key_signer_surfaces_a_refusal():
    run = Recorder([(1, "existing key must be an owned regular 0600 file")])
    with pytest.raises(jr.RunRefused, match="0600"):
        jr.RegisteredKeySigner(identity="sattler", run=run).advance("r", "claim")


def test_each_shuttle_call_is_bounded_and_the_signer_has_a_total_budget():
    t = [0.0]
    timeouts = []

    def slow(argv, *, timeout):
        timeouts.append(timeout)
        t[0] += 15.0                        # every call eats most of its timeout
        return subprocess.CompletedProcess(argv, 0, "", "")

    s = jr.RegisteredKeySigner(identity="sattler", run=slow, clock=lambda: t[0])
    s.advance("r", "work")
    s.advance("r", "report")                # 15s in: 5s of the 20s budget left
    with pytest.raises(jr.RunRefused, match="budget"):
        s.advance("r", "report")            # 30s in: refused without calling shuttle
    assert timeouts == [jr.CALL_TIMEOUT, 5.0]


def test_a_hung_shuttle_is_a_refusal_not_a_stall():
    def hang(argv, *, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)
    with pytest.raises(jr.RunRefused, match="TimeoutExpired"):
        jr.RegisteredKeySigner(identity="sattler", run=hang).advance("r", "claim")


# --- wiring: the ledger carries the run through spawn, live and finish --------

def test_ledger_job_run_from_spawn_to_report(tmp_path):
    s = FakeSigner()
    root = tmp_path
    eph.write(root, dict(_rec(), state=eph.LAUNCHING, result=None))
    eph.run_begin(root, "eph-task-abc123", signer_for=lambda rec: s)
    assert eph.read(root, "eph-task-abc123")["shuttle_run"]["state"] == "spawned"
    eph.run_step(root, "eph-task-abc123", "claim", signer_for=lambda rec: s)
    eph.run_end(root, "eph-task-abc123", "done", signer_for=lambda rec: s)
    run = eph.read(root, "eph-task-abc123")["shuttle_run"]
    assert (run["state"], run["steps"]) == ("reported", ["claim", "work", "report"])


def test_a_claim_racing_the_ending_loses_no_signed_step(tmp_path):
    """Review of #758: run_step and run_end read the entry outside any lock and
    wrote it whole, so the later store could drop a step shuttle had signed.
    The per-job run lock makes the ending see the claim. Shown failing: with
    run_lock replaced by a no-op the ender reads while the claim is unsigned."""
    import threading
    root = tmp_path
    eph.write(root, dict(_rec(), state=eph.LAUNCHING, result=None))
    eph.run_begin(root, "eph-task-abc123", signer_for=lambda rec: FakeSigner())
    in_claim, release = threading.Event(), threading.Event()

    class SlowClaim(FakeSigner):
        def advance(self, run, step):
            if step == "claim":
                in_claim.set()
                release.wait(5)
            super().advance(run, step)

    claim = threading.Thread(target=eph.run_step,
                             args=(root, "eph-task-abc123", "claim"),
                             kwargs={"signer_for": lambda rec: SlowClaim()})
    claim.start()
    assert in_claim.wait(5)
    ender_read = threading.Event()

    def ender_signer(rec):                  # called only AFTER the ender has read
        ender_read.set()
        return FakeSigner()

    ender = threading.Thread(target=eph.run_end, args=(root, "eph-task-abc123", "done"),
                             kwargs={"signer_for": ender_signer})
    ender.start()
    # The claim is still unsigned: the ender must be BLOCKED, not reading. With
    # run_lock a no-op this fails here, deterministically, before any release.
    assert not ender_read.wait(0.5)
    release.set()
    claim.join(5), ender.join(5)
    run = eph.read(root, "eph-task-abc123")["shuttle_run"]
    assert (run["state"], run["steps"]) == ("reported", ["claim", "work", "report"])


class Exploding(FakeSigner):
    """A signer failing with something OTHER than RunRefused (review of #758)."""

    def start(self, defn, run):
        raise OSError("read-only TMPDIR")

    def advance(self, run, step):
        raise OSError("read-only TMPDIR")


@pytest.mark.parametrize("op", ["begin", "step", "end"])
def test_a_non_refusal_failure_is_recorded_not_raised(tmp_path, op):
    root, name = tmp_path, "eph-task-abc123"
    eph.write(root, dict(_rec(), state=eph.LAUNCHING, result=None))
    if op != "begin":
        eph.run_begin(root, name, signer_for=lambda rec: FakeSigner())
    call = {"begin": lambda: eph.run_begin(root, name, signer_for=lambda rec: Exploding()),
            "step": lambda: eph.run_step(root, name, "claim", signer_for=lambda rec: Exploding()),
            "end": lambda: eph.run_end(root, name, "done", signer_for=lambda rec: Exploding())}[op]
    assert call() is None
    assert "OSError" in eph.read(root, name)["shuttle_run"]["error"]


def test_a_stale_definition_is_refused_not_a_keyerror():
    rec = dict(_rec(), shuttle_run={"run": "r", "definition": "gone-v0", "state": "claimed"})
    with pytest.raises(jr.RunRefused, match="unknown run definition"):
        jr.step(rec, "work", FakeSigner())
    assert "unknown run definition" in jr.end(rec, "done", FakeSigner())["error"]


def test_signer_temp_file_failure_is_a_refusal(monkeypatch):
    def boom(*a, **k):
        raise OSError("No space left on device")
    monkeypatch.setattr(jr.tempfile, "NamedTemporaryFile", boom)
    signer = jr.RegisteredKeySigner(identity="sattler",
                                    run=lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(jr.RunRefused, match="No space left"):
        signer.define(jr.TASK)


def test_finish_still_reports_and_tears_down_when_the_run_explodes(tmp_path, monkeypatch):
    """Shown failing: drop the guard in run_end and the OSError escapes finish
    before notify and schedule_teardown run."""
    root, name = tmp_path, "eph-task-abc123"
    eph.write(root, dict(_rec(), state=eph.LIVE, result=None))
    eph.run_begin(root, name, signer_for=lambda rec: FakeSigner())
    monkeypatch.setattr(jr, "signer_for", lambda rec: Exploding())
    notified, scheduled = [], []
    monkeypatch.setattr(eph, "notify",
                        lambda rec, **kw: notified.append(rec["name"]) or [])
    eph.finish(root, name, "done", "did it", "", persist_event=None, comment=None,
               schedule_teardown=scheduled.append, now=1.0)
    assert notified == [name] and scheduled == [name]
    assert "OSError" in eph.read(root, name)["shuttle_run"]["error"]


def test_teardown_removes_the_run_lock(tmp_path):
    root, name = tmp_path, "eph-task-abc123"
    eph.write(root, dict(_rec(), state=eph.LAUNCHING, result=None))
    eph.run_begin(root, name, signer_for=lambda rec: FakeSigner())
    lockfile = eph.ledger_dir(root) / f".run-{name}.lock"
    assert lockfile.exists()
    eph.teardown(root, name, kill_session=lambda s: None, git=lambda *a, **k: None)
    assert not lockfile.exists()


def test_a_job_run_is_started_once(tmp_path):
    eph.write(tmp_path, dict(_rec(), state=eph.LAUNCHING, result=None))
    s = FakeSigner()
    assert eph.run_begin(tmp_path, "eph-task-abc123", signer_for=lambda rec: s)
    assert eph.run_begin(tmp_path, "eph-task-abc123", signer_for=lambda rec: s) is None


def test_ledger_job_with_runs_off_records_why(tmp_path):
    eph.write(tmp_path, dict(_rec(), state=eph.LAUNCHING, result=None))
    eph.run_begin(tmp_path, "eph-task-abc123")          # suite runs with runs off
    run = eph.read(tmp_path, "eph-task-abc123")["shuttle_run"]
    assert run["state"] is None and run["error"]
    assert eph.run_end(tmp_path, "eph-task-abc123", "done") is None


# --- the real shuttle CLI: verify passes for the current signer ---------------

def _shuttle_python():
    exe = shutil.which("shuttle")
    if not exe:
        return None
    first = Path(os.path.realpath(exe)).read_text(errors="replace").splitlines()[:1]
    py = first[0][2:].strip() if first and first[0].startswith("#!") else ""
    return py if py and Path(py).is_file() else None


_VERIFY = r"""
import json, sys
from pathlib import Path
from shuttle import signing, export
log, key_dir, run_id, tamper = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4] == "1"
events = [r for r in map(json.loads, open(log)) if r.get("type") == "transition" and r["run"] == run_id]
ok = []
for e in events:
    pk = signing.public_key_hex(e["agent"], key_dir)
    sig = ("00" * 64) if tamper else e["signature"]
    ok.append(signing.verify_transition(pk, sig, export.run_iri(run_id), e["step"],
                                        e["from"], e["to"], e["at"], e["agent"]))
print(json.dumps({"n": len(events), "ok": ok}))
"""


@pytest.mark.skipif(_shuttle_python() is None, reason="shuttle CLI not installed")
def test_real_shuttle_run_verifies_for_the_registered_key_signer(tmp_path, monkeypatch):
    state, keys = tmp_path / "state", tmp_path / "keys"
    monkeypatch.setenv("SHUTTLE_STATE_DIR", str(state))
    monkeypatch.setenv("SHUTTLE_KEY_DIR", str(keys))   # a test key, never the crew's
    subprocess.run(["shuttle", "keys", "init", "admin"], check=True,
                   capture_output=True, timeout=60)
    s = jr.RegisteredKeySigner(identity="admin", binary=shutil.which("shuttle"))
    rec = dict(_rec(), administrator="admin")
    rec["shuttle_run"] = jr.begin(rec, s)
    assert rec["shuttle_run"]["error"] is None
    jr.step(rec, "claim", s)
    assert jr.end(rec, "done", s)["state"] == "reported"
    log = next(state.glob("*.jsonl"))

    def verify(tamper):
        out = subprocess.run([_shuttle_python(), "-I", "-c", _VERIFY, str(log), str(keys),
                              rec["name"], "1" if tamper else "0"],
                             capture_output=True, text=True, timeout=60, check=True)
        return json.loads(out.stdout)

    good = verify(False)
    assert good == {"n": 3, "ok": [True, True, True]}
    assert verify(True)["ok"] == [False, False, False]      # the check can say no
    # shuttle itself refuses the illegal step too, not only st's mirror of it.
    with pytest.raises(jr.RunRefused):
        s.advance(rec["name"], "claim")
    # No job identity was ever given a key: the only key is the registered one.
    assert sorted(p.stem for p in keys.glob("*.pk8")) == ["admin"]


@pytest.mark.skipif(_shuttle_python() is None, reason="shuttle CLI not installed")
def test_real_shuttle_refuses_an_unregistered_signer_and_mints_no_key(tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    keys.mkdir()
    monkeypatch.setenv("SHUTTLE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SHUTTLE_KEY_DIR", str(keys))
    s = jr.RegisteredKeySigner(identity="eph-task-abc123", binary=shutil.which("shuttle"))
    rec = dict(_rec(), administrator="eph-task-abc123")
    rec["shuttle_run"] = jr.begin(rec, s)
    # Review of #758: without these, a refused START left state None and step()
    # raised "no started run", passing without the key ever being asked for.
    assert rec["shuttle_run"]["error"] is None and rec["shuttle_run"]["state"] == "spawned"
    with pytest.raises(jr.RunRefused, match="signing key"):
        jr.step(rec, "claim", s)
    assert rec["shuttle_run"]["state"] == "spawned"
    assert list(keys.iterdir()) == []
