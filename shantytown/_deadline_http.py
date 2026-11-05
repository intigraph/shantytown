"""One foreground HTTP read with a total deadline and bounded response.

The child owns DNS, connection setup, headers and body consumption. The parent
kills and reaps it on expiry, including when a peer keeps making slow progress.
Request headers travel over a private stdin pipe, never in process arguments.
There is no persistent worker, retry or fallback transport.

# arming: library; the governed responsibility/metrics reader is the caller.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import time

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 512 * 1024


def post(url, body, headers, *, timeout, max_bytes):
    if (isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0
            or type(max_bytes) is not int or not 0 < max_bytes <= MAX_RESPONSE_BYTES):
        raise ValueError("invalid bounded HTTP budget")
    deadline = time.monotonic() + timeout
    packet = json.dumps({"url": url, "body": body, "headers": headers,
                         "timeout": timeout, "max_bytes": max_bytes}).encode()
    if len(packet) > MAX_REQUEST_BYTES:
        raise ValueError("HTTP request byte cap reached")
    if time.monotonic() >= deadline:
        raise TimeoutError("HTTP total deadline exceeded")
    with subprocess.Popen(
        [sys.executable, "-I", "-S", str(Path(__file__).resolve())],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as child:
        try:
            # Popen creation is synchronous; subtract its elapsed time too.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("HTTP total deadline exceeded")
            body, _ = child.communicate(input=packet, timeout=remaining)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
            raise TimeoutError("HTTP total deadline exceeded") from None
        except BaseException:
            child.kill()
            child.communicate()
            raise
    if time.monotonic() >= deadline:
        raise TimeoutError("HTTP total deadline exceeded")
    if child.returncode:
        raise OSError("HTTP request unavailable")
    if len(body) > max_bytes:
        raise ValueError("HTTP response byte cap reached")
    return body


def _worker():
    # No package imports/config discovery: the parent's already-attributed
    # request is the entire input. Never print exception text or headers.
    from urllib.request import Request, urlopen
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            return 2
        request = json.loads(raw)
        limit = request["max_bytes"]
        if type(limit) is not int or not 0 < limit <= MAX_RESPONSE_BYTES:
            return 2
        req = Request(request["url"], data=request["body"].encode(),
                      headers=request["headers"])
        with urlopen(req, timeout=request["timeout"]) as response:
            body = response.read(limit + 1)
        sys.stdout.buffer.write(body)
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(_worker())
