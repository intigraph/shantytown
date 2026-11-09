"""Runtime updates use the ordinary checkpointed, idle cycle executor.

One locally owned process at a time. A successful launch is not a version
receipt: the next exact-session observation must prove the target version
before another replacement is admitted. Peers run their own local tend sweep.
"""
from pathlib import Path
import fcntl
import json
import os
import time

from . import runtime_update
from .files import write_json_atomic


def _read(root):
    try:
        value = json.loads((Path(root) / "notify" / "runtime-roll.json").read_text())
        return value if isinstance(value, dict) and all(isinstance(v, dict) for v in value.values()) else None
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None


def ledger(root):
    return _read(root) or {}


def sweep(root, cards, *, requests, boundary, checkpoint, preflight,
          observe=None, log=lambda text: None, fleet_block=""):
    directory = Path(root) / "notify"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / "runtime-roll.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("runtime-roll: another pass owns admission; deferred")
            return []
        return _sweep(root, cards, requests=requests, boundary=boundary,
                      checkpoint=checkpoint, preflight=preflight, observe=observe,
                      log=log, fleet_block=fleet_block)
    finally:
        os.close(descriptor)


def _sweep(root, cards, *, requests, boundary, checkpoint, preflight,
           observe, log, fleet_block):
    observe = observe or runtime_update.for_agent
    book = _read(root)
    if book is None:
        log("runtime-roll: version ledger UNKNOWN; no replacement requested")
        return []
    pending = runtime_update.pending_cycles(root)
    if pending is None:
        log("runtime-roll: cycle requests UNKNOWN; no replacement requested")
        return []
    active = False
    eligible = []
    for card in sorted(cards, key=lambda c: c.name):
        if card.retired:
            continue
        evidence = observe(root, card.name)
        old = book.get(card.name, {})
        meta = (pending.get(card.name) or {}).get("runtime_update")
        if meta and old.get("phase") not in ("requested", "awaiting-version"):
            # A request may have committed before a failed version-ledger write.
            # Recover its generation, never silently treat it as a manual cycle.
            old = dict(old, phase="requested", target=meta.get("installed"),
                       previous=meta.get("running"), source_session=meta.get("session"))
        row = dict(session=evidence.session, running=evidence.running,
                   installed=evidence.installed, harness=evidence.harness,
                   observed_at=time.time())
        if old.get("receipt"):
            row["receipt"] = old["receipt"]
        if old.get("phase") in ("requested", "awaiting-version"):
            target = old.get("target")
            row.update(target=target, previous=old.get("previous"),
                       source_session=old.get("source_session"))
            if (evidence.session and evidence.session != old.get("source_session")
                    and runtime_update.version(evidence.running) is not None
                    and runtime_update.version(target) is not None
                    and runtime_update.version(evidence.running) >= runtime_update.version(target)):
                row["phase"] = "completed"
                row["receipt"] = dict(before=old.get("previous"), after=evidence.running,
                                      requested=target,
                                      source_session=old.get("source_session"),
                                      session=evidence.session, verified_at=time.time())
                log(f"runtime-roll: {card.name} verified {old.get('previous')} -> {evidence.running}")
            else:
                row["phase"] = ("requested" if card.name in pending else "awaiting-version")
                row["reason"] = (pending.get(card.name, {}).get("refused") or {}).get(
                    "reason", "waiting for exact new-session version receipt")
                active = True
        elif not evidence.outdated:
            row["phase"] = "current" if evidence.running and evidence.installed else "unknown"
        elif card.name in pending:
            row.update(phase="waiting", reason="existing cycle request retained")
            active = True
        elif runtime_update._manual_keep(root, card.name):
            row.update(phase="held", reason="fresh manual KEEP")
        else:
            row.update(phase="waiting", reason="waiting for safe idle boundary")
            # Failed checkpoint writes are not automatically replayed. The
            # operator must resolve/rearm this exact version generation.
            if old.get("phase") == "checkpoint-failed" and old.get("key") == evidence.key:
                row.update(phase="checkpoint-failed", key=evidence.key,
                           reason=old.get("reason"))
            else:
                eligible.append((card, evidence, row))
        book[card.name] = row
    requested = []
    if fleet_block:
        for _, _, row in eligible:
            row["reason"] = fleet_block
        log(f"runtime-roll: {fleet_block}; no new replacement")
    if not active and not fleet_block:
        for card, evidence, row in eligible:
            try:
                refusal = boundary(card)
                if refusal:
                    row["reason"] = refusal
                    continue
                preflight(card)
            except Exception as exc:
                row.update(phase="blocked", reason=f"preflight: {exc}")
                continue
            try:
                snapshot = checkpoint(card, evidence)
                if not snapshot.get("text"):
                    raise ValueError("empty automatic checkpoint")
            except Exception as exc:
                row.update(phase="checkpoint-failed", key=evidence.key,
                           reason=f"checkpoint unproven: {exc}")
                log(f"runtime-roll: {card.name}: {row['reason']}; no request")
                continue
            # Publish the peer-visible reservation BEFORE committing a cycle.
            # If either this write or the later final ledger write fails, a
            # peer must never see "current" alongside an accepted request.
            # An uncertain request outcome leaves this reservation fenced.
            row.update(phase="requested", target=evidence.installed,
                       previous=evidence.running, source_session=evidence.session)
            write_json_atomic(Path(root) / "notify" / "runtime-roll.json", book)
            # Requests is durable, serialized and shared with manual/context
            # cycles. Never replace a request another caller just accepted.
            admitted = requests.request(
                card.name, snapshot["text"], snapshot.get("item", ""),
                snapshot.get("nodes", []), no_in_place=True, auto=True,
                runtime_update=dict(key=evidence.key, session=evidence.session,
                                    running=evidence.running, installed=evidence.installed,
                                    checkpoint=snapshot["text"]), only_if_absent=True)
            if not admitted:
                row.update(phase="waiting", reason="another cycle request won admission")
                break
            row.update(phase="requested", target=evidence.installed,
                       previous=evidence.running, source_session=evidence.session)
            requested.append(card.name)
            log(f"runtime-roll: requested {card.name} {evidence.running} -> {evidence.installed}")
            break
    path = Path(root) / "notify" / "runtime-roll.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, book)
    return requested


def peer_block(results):
    """Fresh peer rows must show no admitted, unverified runtime replacement."""
    for result in results:
        if result.get("error"):
            return "peer runtime census UNKNOWN"
        for row in result.get("agents", []):
            state = row.get("runtime_update")
            if isinstance(state, dict) and state.get("phase") in ("requested", "awaiting-version"):
                return f"peer {result['host']}/{row['name']} has an unverified replacement"
            phases = {"current", "unknown", "waiting", "held", "blocked", "checkpoint-failed", "completed"}
            if row.get("live") and (not isinstance(state, dict) or state.get("phase") not in phases):
                return "peer runtime roll metadata unavailable; refresh peer st first"
    return ""


def checkpoint_gate(root, agent, request, comments):
    """A machine snapshot must be read back verbatim, bound to this session.

    It is attributed to st's actual writer, never falsely to the target agent.
    Ordinary/manual cycle checkpoint policy is unchanged.
    """
    from .cycle import DurableGate
    meta = request.get("runtime_update") or {}
    evidence = runtime_update.for_agent(root, agent)
    text = meta.get("checkpoint")
    requested = runtime_update.version(meta.get("installed"))
    installed = runtime_update.version(evidence.installed)
    valid = (evidence.outdated and requested is not None and installed is not None
             and installed >= requested and meta.get("running") == evidence.running
             and meta.get("session") == evidence.session
             and isinstance(text, str) and bool(text)
             and request.get("checkpoint") == text)
    item = request.get("checkpoint_bead", "")
    if item:
        valid = valid and any(c.get("text") == text for c in comments)
    return DurableGate(agent, item, "automatic runtime checkpoint", bool(valid),
                       checkpoint=text if valid else "")
