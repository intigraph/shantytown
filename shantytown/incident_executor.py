"""Signed verdict -> fix-seed executor, bound to the frozen launch input (za4f.6.2, step H2).

Takes one triage report record and creates AT MOST ONE fix seed from it. Source only:
nothing here launches a job, signs, or touches a live board; the verifier and the board
are injected, so the real signed reader and the real seeds board arrive in a later step.

Order of refusals, each recorded (never dropped) in the H1 journal:
  1. `frozen-digest`    the caller's frozen launch input no longer hashes to the digest
                        recorded at launch (`frozen_sha256`): the input was changed after
                        launch, so nothing downstream can be trusted to match it.
  2. `unsigned`         no verifier, or the verifier raised / returned no identity.
  3. `wrong-signer`     the verified identity is not `expected_signer` (launch state).
  4. any H1 refusal     (`incident-binding`, `launch-mismatch`, spec refusals, ...): the
                        verdict is about a different incident than the frozen input.
The seed is built from the validated report and the frozen input only, never from live
board or host state. Only the `file-followup` intent creates a seed; a verdict whose
spec routes no `file-followup` creates none and says `no-fix-route`.

Idempotence: the board is asked for an existing seed with this intent's idempotency key
BEFORE creating, and the key is written into the seed. A crash between create and the
local record is therefore recovered by the redelivery (found by key, not created again).
A board or journal fault is FATAL (the exception propagates): the caller redelivers.
"""
from dataclasses import dataclass
import os
from typing import Callable, Protocol

from shantytown.incident_consumer import (
    RECORD_CAP, Consumed, _canonical, _create_once, _digest, _journal_dir_ok, _refuse, consume)
from shantytown.incident_report import Refusal

FIX_ACTION = 'file-followup'
KEY_MARKER = 'idempotency-key: '
TITLE_LIMIT = 200


class Board(Protocol):
    def find(self, key: str) -> str | None: ...
    def create(self, title: str, description: str, key: str) -> str: ...


@dataclass(frozen=True)
class Executed:
    run_id: str
    seed_id: str
    key: str
    replay: bool


def frozen_digest(frozen) -> str:
    """The digest the launcher records when it freezes the input."""
    return _digest(frozen)


def _seed_text(frozen: dict, args: dict, key: str) -> tuple[str, str]:
    fix = args['report']['proposed_fix']
    title = f"fix: {frozen['fingerprint_kind']} {frozen['fingerprint']} on {frozen['item']}"[:TITLE_LIMIT]
    # Every value below is untrusted report text, rendered as quoted data under fixed labels.
    body = '\n'.join([
        f"incident: {frozen['fingerprint_kind']} {frozen['fingerprint']} onset {frozen['onset_utc']}",
        f"carrier item: {frozen['item']}",
        f"repo: {fix['repo']}", f"scope: {fix['scope']}", f"verification: {fix['verification']}",
        f"diagnosis: {args['report']['diagnosis']}",
        f"summary: {args['summary']}",
        f"{KEY_MARKER}{key}"])
    return title, body


def execute(record, *, frozen, frozen_sha256: str, jobspec, journal: str, verify: Callable | None,
            expected_signer: str, board: Board) -> Executed | Refusal:
    """Create the one fix seed for a signed, frozen-bound verdict, or refuse and say why."""
    if not _journal_dir_ok(journal):
        return Refusal('journal-dir')
    if frozen_digest(frozen) != frozen_sha256:
        return _refuse(journal, 'frozen-digest', record, frozen, jobspec)
    signer = None
    if verify is not None:
        try:
            signer = verify(record)
        except Exception:  # any verifier failure is "not signed"; its text is never trusted
            signer = None
    if not isinstance(signer, str) or not signer:
        return _refuse(journal, 'unsigned', record, frozen, jobspec)
    if signer != expected_signer:
        return _refuse(journal, 'wrong-signer', record, frozen, jobspec)
    consumed = consume(record, frozen=frozen, jobspec=jobspec, journal=journal, verified=True)
    if isinstance(consumed, Refusal):
        return consumed
    intent = next((i for i in consumed.intents if i.action == FIX_ACTION), None)
    if intent is None:
        return _refuse(journal, 'no-fix-route', record, frozen, jobspec)
    done = os.path.join(journal, 'executed-' + intent.idempotency_key + '.json')
    seed_id = board.find(intent.idempotency_key)
    replay = seed_id is not None
    if not replay:
        title, body = _seed_text(frozen, intent.args, intent.idempotency_key)
        seed_id = board.create(title, body, intent.idempotency_key)
    entry = (_canonical({'version': 1, 'run_id': consumed.run_id, 'key': intent.idempotency_key,
                         'seed_id': seed_id}) + '\n').encode()
    if len(entry) > RECORD_CAP:
        return _refuse(journal, 'record-too-large', record, frozen, jobspec)
    # Existing record wins: a replay never rewrites it; a first run after a crash adds it.
    _create_once(journal, os.path.basename(done), entry)
    return Executed(consumed.run_id, seed_id, intent.idempotency_key, replay)


__all__ = ['Board', 'Executed', 'execute', 'frozen_digest', 'Refusal']
