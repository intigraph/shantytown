"""Current provider refusals are holds, never automatic recovery signals."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

_BANNER = re.compile(r"^● (?:API Error: )?[^\n]{0,100}?safeguards "
                     r"(?:flagged this message|stopped the response)\b")
_REQUEST = re.compile(r"\breq_[A-Za-z0-9_]{1,96}\b")


def current(plain: str) -> str:
    """Read only the latest response, bounded above the final input chrome.

    A later assistant response or /clear retires an old banner. The final
    composer can contain a placeholder: it is not evidence of a new response.
    Line anchors exclude quoted logs/source. Missing request IDs stay UNKNOWN.
    """
    lines = plain.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    lines = lines[-40:]
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^❯\s*/clear(?:\s|$)", line):
            start = None
        elif line.startswith("● "):
            start = i if _BANNER.match(line) else None
    return "\n".join(lines[start:]) if start is not None else ""


def request_ids(plain: str) -> list[str]:
    return sorted(set(_REQUEST.findall(current(plain))))


def _save(path, value):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".report-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def notify(root, agent, ids, fallback_key, text, record, deliver, log=lambda text: None):
    directory = Path(root) / "safeguard-reports"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(json.dumps([agent, ids or fallback_key]).encode()).hexdigest()
    path = directory / (key + ".json")
    with (directory / ".delivery-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            previous = json.loads(path.read_text())
            if previous.get("state") != "delivered":
                log(f"safeguard report UNKNOWN for {agent}: inspect {path}; not retried")
            return False
        record = dict(record, state="pending")
        _save(path, record)
        try:
            receipt = deliver(text)
            if not receipt:
                raise RuntimeError("durable delivery not confirmed")
        except Exception:
            record["state"] = "UNKNOWN"
            _save(path, record)
            raise
        record.update(state="delivered", receipt=str(receipt))
        _save(path, record)
        return True


def report(root, findings, agents, panes, plate, deliver, log):
    """One persist-first admin report per observed refusal; no pane input.

    Reserve before delivery: a lost write response must not create a duplicate
    inbox on the next tick. Pending/UNKNOWN reservations stay loud for review.
    Dependencies are injected so fixture replay cannot touch a real inbox.
    """
    from .tend import SAFEGUARD_BLOCKED
    cards = {card.name: card for card in agents}
    directory = Path(root) / "safeguard-reports"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    sent = []
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for finding in findings:
            if finding.verdict != SAFEGUARD_BLOCKED:
                continue
            card = cards[finding.agent]
            from .triage import strip_attrs
            plain = strip_attrs(panes.capture(card.pane, attrs=True))
            block = current(plain)
            if not block:
                log(f"safeguard report: {card.name} changed; no current refusal")
                continue
            ids = request_ids(plain)
            # Chrome counters can change every tick. Without a request ID,
            # dedup by the refusal banner, not the surrounding moving footer.
            key = hashlib.sha256(json.dumps([card.name, ids or block.splitlines()[0]]).encode()).hexdigest()
            path = directory / (key + ".json")
            if path.exists():
                previous = json.loads(path.read_text())
                if previous.get("state") != "delivered":
                    log(f"safeguard report UNKNOWN for {card.name}: inspect {path}; not retried")
                continue
            try:
                items = ",".join(str(item.id) for item in plate(card.name)) or "none"
            except Exception:
                items = "UNKNOWN"
            shown_ids = ",".join(ids[:2]) or "UNKNOWN"
            if len(ids) > 2:
                shown_ids += f" (+{len(ids) - 2} in report ledger)"
            text = (f"safeguard-blocked agent={card.name[:32]}; requests={shown_ids}; "
                    f"plate={items[:64]}. Held: no automatic input/cycle/model switch. "
                    "Administrator review required.")
            # Preserve bounded, attributable metadata only, never pane content.
            record = {"agent": card.name, "requests": ids, "plate": items,
                      "state": "pending"}
            if notify(root, card.name, ids, block.splitlines()[0], text, record, deliver, log):
                sent.append(card.name)
    return sent
