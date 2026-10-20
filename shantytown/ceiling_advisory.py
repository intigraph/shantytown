"""Observation at the existing fleet sweep; never an eligibility/dispatch path.

# arming: library called by the existing natural tend ceiling-transfer sweep.

Rows are UNGRADED, including refusals and unknown inputs. A planned row without
an outcomes row does not prove delivery or refusal. Policy effect stays record;
independent adjudication must name the observed policy/code identities and all
unknown/ungraded populations before quoting a false-positive rate.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

POLICY = "policy_ceiling-held-work-moves-to-available-harness"
POLICY_VERSION = "4e83e01ae8985b24"  # governed replacement promotion, not effect raise


def _value(value):
    if dataclasses.is_dataclass(value):
        return {f.name: _value(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("unsupported advisory input")


class Capture:
    """Best-effort local observations; no new tracker, budget or runtime reads."""

    def __init__(self, root: Path, *, dry_run: bool, log):
        self.root, self.dry_run, self.log = root, dry_run, log
        self.sweep = uuid.uuid4().hex

    def record(self, phase: str, **inputs) -> None:
        # A diagnostic must never turn an accepted handoff into a failed one,
        # or prevent the normal dispatcher from applying its own gates.
        try:
            identities = {}
            for name in ("ceiling_advisory.py", "ceiling_transfer.py", "cli.py"):
                identities[name] = hashlib.sha256(
                    Path(__file__).with_name(name).read_bytes()).hexdigest()
            row = dict(schema=1, policy=POLICY, policy_version=POLICY_VERSION,
                       effect="record", adjudication="ungraded", ts=time.time(),
                       sweep=self.sweep, phase=phase, dry_run=self.dry_run,
                       code=identities, inputs=_value(inputs))
            # One append syscall, private by default; no shared state used for
            # eligibility. Existing root permissions remain authoritative.
            data = (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode()
            fd = os.open(self.root / "ceiling-transfer-advisory.jsonl",
                         os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                if os.write(fd, data) != len(data):
                    raise OSError("incomplete advisory append")
            finally:
                os.close(fd)
        except Exception as exc:  # noqa: BLE001 - observation cannot alter dispatch
            self.log("ceiling-transfer: advisory capture UNKNOWN (" + type(exc).__name__ + ")")
