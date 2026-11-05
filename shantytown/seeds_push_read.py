"""Opt-in local projection reads through the Seeds SDK, never a second applier."""
from __future__ import annotations

import json
import os
import subprocess

from .query_identity import sdk_subprocess_options


def enabled() -> bool:
    value = os.environ.get("ST_SEEDS_PUSH_READS", "0")
    if value not in ("0", "1"):
        raise ValueError("ST_SEEDS_PUSH_READS must be 0 or 1")
    return value == "1"


def read(proof, query: str, timeout: int) -> dict:
    """SDK owns config, private IPC and proof validation; errors never poll."""
    if not proof.quipu_url or not proof.graph or timeout <= 0:
        raise ValueError("push read UNKNOWN: authoritative board binding missing")
    payload = json.dumps({"query": query}).encode()
    if len(payload) > 60 * 1024:
        raise ValueError("push read UNKNOWN: projection query exceeds budget")
    try:
        child = subprocess.run(
            [os.environ.get("SHANTY_SD_BIN", "sd"), "--quipu", proof.quipu_url,
             "--graph", proof.graph, "read-stream-query"],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=min(timeout, 5), check=False,
            **sdk_subprocess_options(read_operation="push-projection"),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("push read UNKNOWN: local SDK unavailable; no polling fallback") from error
    if child.returncode or len(child.stdout) > 8 * 1024 * 1024:
        raise ValueError("push read UNKNOWN: SDK refused or response exceeded budget")
    try:
        result = json.loads(child.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError("push read UNKNOWN: malformed SDK response") from error
    if not isinstance(result, dict):
        raise ValueError("push read UNKNOWN: malformed SDK response")
    return result
