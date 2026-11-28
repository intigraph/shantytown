"""job_runs — every ephemeral job is ONE Shuttle workflow run (aegis-za4f.19.1).

Measured 2026-11-27 (sattler): ephemeral jobs started no Shuttle run and signed
no transition, so "what did this job do, and who says so" had no signed record.
This module makes each job one run: started at spawn, advanced on the job's
steps (claimed when its prompt is delivered, then its work and PR steps), and
ended when it reports. The lifecycle is the za4f.17.2 code-change vocabulary
cut down to what a job performs; `TASK` and `REVIEW` below are the definitions.

THE SIGNER IS AN INTERFACE, and that is the point of this slice. The ruling on
aegis-za4f.19 (sattler, option B) is a signing BROKER under its own uid, holding
per-job keys a same-uid job cannot read. Until it exists the only signer is
`RegisteredKeySigner`: the `shuttle` CLI with `--require-existing-keys`, signing
as the job's administrator, whose key is already registered. Two consequences
are deliberate and recorded rather than papered over:

- NO per-job key is generated, injected or passed — not in env, argv, a file or
  an fd (2026-09-12 decision 3: for same-uid agents those are theatre). Every
  signing call carries `--require-existing-keys`, so shuttle REFUSES rather than
  minting an `eph-*` key on first use.
- The signature attributes the transition to the administrator's registered
  key, not to the job. The 2026-09-12 caveat (signatures are not attribution
  for same-uid agents) still stands for this signer; the broker removes it.

Recording a run never blocks a job: spawn, report and teardown must still end a
job that cannot reach Shuttle. Every failure is written to the ledger under
`shuttle_run` so a job with no run says so instead of looking like it had one.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

#: Versioned names: a changed lifecycle is a NEW definition. Re-defining the
#: same name would let one run's history fold against another's edges.
TASK = {
    "name": "st-ephemeral-task-v1",
    "initial": "spawned",
    "terminal": ["reported", "failed"],
    "transitions": [
        {"step": "claim", "from": "spawned", "to": "claimed"},
        {"step": "work", "from": "claimed", "to": "worked"},
        {"step": "open-pr", "from": "worked", "to": "pr-open"},
        {"step": "report", "from": "claimed", "to": "reported"},
        {"step": "report", "from": "worked", "to": "reported"},
        {"step": "report", "from": "pr-open", "to": "reported"},
        {"step": "fail", "from": "spawned", "to": "failed"},
        {"step": "fail", "from": "claimed", "to": "failed"},
        {"step": "fail", "from": "worked", "to": "failed"},
        {"step": "fail", "from": "pr-open", "to": "failed"},
    ],
}
REVIEW = {
    "name": "st-ephemeral-review-v1",
    "initial": "spawned",
    "terminal": ["enqueued", "reported", "changes-requested", "rejected", "failed"],
    "transitions": [
        {"step": "claim", "from": "spawned", "to": "claimed"},
        {"step": "approve", "from": "claimed", "to": "approved"},
        {"step": "request-changes", "from": "claimed", "to": "changes-requested"},
        {"step": "reject", "from": "claimed", "to": "rejected"},
        {"step": "enqueue", "from": "approved", "to": "enqueued"},
        # Approved but not enqueued by this job (no merge queue on the repo):
        # the run still ends, and says it ended short of the queue.
        {"step": "report", "from": "approved", "to": "reported"},
        {"step": "fail", "from": "spawned", "to": "failed"},
        {"step": "fail", "from": "claimed", "to": "failed"},
        {"step": "fail", "from": "approved", "to": "failed"},
    ],
}
DEFINITIONS = {d["name"]: d for d in (TASK, REVIEW)}


class RunRefused(Exception):
    """A transition the definition or the signer does not allow. Message = why."""


def definition_for(job: str | None) -> dict:
    """Review jobs end on a verdict; every other job kind is the task shape."""
    return REVIEW if job == "review" else TASK


def next_state(defn: dict, current: str, step: str) -> str:
    """The state `step` from `current` reaches, or RunRefused naming what WAS
    legal. Checked here before any signer is asked, so an illegal step never
    reaches a key — and checked again by shuttle, which owns the truth."""
    if current in defn["terminal"]:
        raise RunRefused(f"run is terminal ('{current}'); no step advances a finished run")
    legal = [t for t in defn["transitions"] if t["from"] == current]
    for t in legal:
        if t["step"] == step:
            return t["to"]
    raise RunRefused(f"step '{step}' is not legal from state '{current}' in "
                     f"{defn['name']}. Legal here: {sorted({t['step'] for t in legal})}")


def ending_steps(defn: dict, current: str, verdict: str, *, pr: bool = False) -> list[str]:
    """The steps a report walks from `current` to a terminal state.

    Only what the result evidences: a review's verdict IS its step; a task that
    reports done passes `work` (and `open-pr` only when `pr` says the job opened
    one), then `report`. A failed/blocked ending, or any verdict the definition has no
    edge for, is `fail` — never a success path the job did not earn.
    """
    if current in defn["terminal"]:
        return []
    if defn is REVIEW:
        path = {"approve": ["approve", "report"],
                "request-changes": ["request-changes"],
                "reject": ["reject"]}.get(verdict)
        if current == "approved" and verdict == "approve":
            path = ["report"]
    elif verdict in ("done", "merged", "enqueued", "approve"):
        path = {"claimed": ["work", "open-pr", "report"] if pr else ["work", "report"],
                "worked": ["open-pr", "report"] if pr else ["report"],
                "pr-open": ["report"]}.get(current)
    else:
        path = None
    if path is None:
        return ["fail"]
    state = current
    try:
        for step in path:                   # a path the edges do not hold is a fail
            state = next_state(defn, state, step)
    except RunRefused:
        return ["fail"]
    return path


class Signer(Protocol):
    """What a job run needs from a signer. The S2 broker implements this same
    surface with a run capability instead of a key name; callers do not change."""

    identity: str

    def define(self, defn: dict) -> None: ...
    def start(self, defn: dict, run: str) -> None: ...
    def advance(self, run: str, step: str) -> None: ...
    def verify(self, run: str) -> str: ...


Runner = Callable[..., subprocess.CompletedProcess]


#: Review of #758: start/define/start (spawn) and work/report (report) were up
#: to three shuttle calls at 60s each, so a hung shuttle stalled `st agent spawn
#: --report` for minutes. A healthy call takes well under a second; each call
#: gets CALL_TIMEOUT and one signer (= one begin/step/end) gets BUDGET in total.
CALL_TIMEOUT = 10.0
BUDGET = 20.0


def _run(argv, *, timeout: float = CALL_TIMEOUT, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kw)


@dataclass
class RegisteredKeySigner:
    """The current signer: the `shuttle` CLI, signing with an EXISTING
    registered key. It never names a key path, never sets a key variable, and
    never lets shuttle generate one — see the module docstring for why."""

    identity: str
    binary: str = "shuttle"
    run: Runner = _run
    budget: float = BUDGET
    clock: Callable[[], float] = time.monotonic
    _deadline: float | None = field(default=None, init=False, repr=False)

    def _call(self, *args: str) -> str:
        argv = [self.binary, "--require-existing-keys", *args]
        now = self.clock()
        if self._deadline is None:
            self._deadline = now + self.budget
        remaining = self._deadline - now
        if remaining <= 0:
            raise RunRefused(f"shuttle time budget ({self.budget:g}s) exhausted "
                             f"before '{args[0]}'")
        try:
            p = self.run(argv, timeout=min(CALL_TIMEOUT, remaining))
        except (OSError, subprocess.SubprocessError) as e:
            raise RunRefused(f"shuttle unavailable: {type(e).__name__}: {e}") from None
        if p.returncode != 0:
            raise RunRefused((p.stderr or p.stdout or f"exit {p.returncode}").strip()[:300])
        return (p.stdout or "").strip()

    def define(self, defn: dict) -> None:
        try:                                # a full or read-only TMPDIR is a refusal
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(defn, f)
        except OSError as e:
            raise RunRefused(f"cannot write workflow definition: {e}") from None
        try:
            self._call("define", f.name)
        finally:
            os.unlink(f.name)

    def start(self, defn: dict, run: str) -> None:
        try:
            self._call("start", defn["name"], run, "--agent", self.identity)
        except RunRefused as e:
            if "unknown workflow" not in str(e):
                raise
            # First run of this version on this host: define, then start once.
            self.define(defn)
            self._call("start", defn["name"], run, "--agent", self.identity)

    def advance(self, run: str, step: str) -> None:
        self._call("advance", run, "--step", step, "--agent", self.identity)

    def verify(self, run: str) -> str:
        return self._call("verify", run)


def signer_for(rec: dict) -> Signer | None:
    """The configured signer for a job, or None when job runs are off.

    `SHANTY_JOB_RUNS=none` is the negative control the adapters doctrine wants
    (and what the test suite runs with, so no test writes the operator's
    shuttle log). A host with no `shuttle` on PATH gets None too, and the
    ledger says so — it never pretends a run exists.
    """
    if os.environ.get("SHANTY_JOB_RUNS", "shuttle") == "none":
        return None
    binary = shutil.which("shuttle")
    identity = rec.get("administrator")
    if not binary or not identity:
        return None
    return RegisteredKeySigner(identity=identity, binary=binary)


def _entry(rec: dict) -> dict:
    return dict(rec.get("shuttle_run") or {})


def _definition(entry: dict) -> dict:
    """A stale or hand-edited ledger entry names no known definition: refuse."""
    try:
        return DEFINITIONS[entry["definition"]]
    except (KeyError, TypeError):
        raise RunRefused(f"unknown run definition {entry.get('definition')!r}") from None


def begin(rec: dict, signer: Signer | None) -> dict:
    """Start the job's run. Returns the `shuttle_run` ledger entry to store."""
    defn = definition_for(rec.get("job"))
    entry = {"run": rec["name"], "definition": defn["name"], "state": None,
             "signer": None, "steps": [], "error": None}
    if signer is None:
        entry["error"] = "no signer configured (SHANTY_JOB_RUNS=none or no shuttle/administrator)"
        return entry
    entry["signer"] = f"{type(signer).__name__}:{signer.identity}"
    try:
        signer.start(defn, rec["name"])
    except RunRefused as e:
        entry["error"] = f"start refused: {e}"
        return entry
    entry["state"] = defn["initial"]
    return entry


def step(rec: dict, name: str, signer: Signer | None) -> dict:
    """Advance one step. Illegal steps raise RunRefused BEFORE the signer is
    asked; a signer refusal is recorded and also raised, so a caller that must
    not block (spawn, report) catches it and a caller that asked fails loud."""
    entry = _entry(rec)
    if not entry.get("state"):
        raise RunRefused(f"job {rec.get('name')} has no started run"
                         + (f" ({entry['error']})" if entry.get("error") else ""))
    defn = _definition(entry)
    to_state = next_state(defn, entry["state"], name)
    if signer is None:
        raise RunRefused("no signer configured")
    try:
        signer.advance(entry["run"], name)
    except RunRefused as e:
        entry["error"] = f"{name} refused: {e}"
        rec["shuttle_run"] = entry
        raise
    entry["state"] = to_state
    entry["steps"] = [*entry.get("steps", []), name]
    entry["error"] = None
    rec["shuttle_run"] = entry
    return entry


def end(rec: dict, verdict: str, signer: Signer | None) -> dict:
    """Walk the run to a terminal state for this result. Stops at the first
    refusal and leaves it on the entry; never raises (the job must still end)."""
    entry = _entry(rec)
    if not entry.get("state"):
        return entry
    try:
        defn = _definition(entry)
    except RunRefused as e:
        entry["error"] = f"end refused: {e}"
        rec["shuttle_run"] = entry
        return entry
    # No job step reports "I opened a PR" to st yet, so a task's ending never
    # claims `open-pr` on the job's say-so; the edge exists for that wiring.
    for name in ending_steps(defn, entry["state"], verdict):
        try:
            step(rec, name, signer)
        except RunRefused:
            break
    return _entry(rec)
