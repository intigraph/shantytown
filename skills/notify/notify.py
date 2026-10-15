#!/usr/bin/env python3
"""notify — push a message to a human, and report exactly what happened to it.

Stdlib only. No packages, no lockfile, no daemon.

This tool reports **acceptance**, never readership. A 200 from a push server
means the server took the bytes. It does not mean a phone buzzed, and it
certainly does not mean a person read it. Every success string here says
"ACCEPTED" for that reason.

Outcomes, one exit code each — because "we told someone" is exactly the claim
you must not make on a guess:

    0  DELIVERED  every configured transport accepted the message
    1  PARTIAL    at least one accepted, at least one failed
    2  FAILED     transports were configured and every one of them failed
    3  UNCONFIG   no transport was configured. NOTHING WAS SENT.

Exit 3 is the one that matters. An escalation path with no transport configured
is the failure mode this tool exists to make loud: it looks like a working
notifier right up until the night it is needed, and a silent no-op that returns
success is indistinguishable from a delivered page.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DELIVERED, PARTIAL, FAILED, UNCONFIG = 0, 1, 2, 3

TIMEOUT = float(os.environ.get("NOTIFY_TIMEOUT", "10"))

# ntfy priorities are 1..5 (min, low, default, high, urgent). The map is a
# default, not a law — override any entry from the environment.
DEFAULT_PRIORITY = {"debug": "1", "info": "3", "warning": "4", "critical": "5"}
SEVERITIES = list(DEFAULT_PRIORITY)


def priority_for(severity: str) -> str:
    env = os.environ.get(f"NOTIFY_PRIORITY_{severity.upper()}")
    return env or DEFAULT_PRIORITY.get(severity, "3")


class Result:
    def __init__(self, transport: str, ok: bool, detail: str, dry: bool = False):
        self.transport, self.ok, self.detail, self.dry = transport, ok, detail, dry

    @property
    def label(self) -> str:
        # A dry run must never print ACCEPTED. Nothing was sent, so nothing was
        # accepted, and the word is the entire claim this tool is careful about.
        if self.dry:
            return "PLANNED "
        return "ACCEPTED" if self.ok else "FAILED  "

    def __str__(self) -> str:
        return f"{self.transport:10s} {self.label}  {self.detail}"


def _post(url: str, data: bytes, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


def send_ntfy(msg: str, title: str, severity: str, tags: str, dry: bool) -> Result | None:
    base = os.environ.get("NTFY_URL")
    topic = os.environ.get("NTFY_TOPIC")
    if not base or not topic:
        return None
    url = base.rstrip("/") + "/" + topic
    headers = {"Priority": priority_for(severity), "Content-Type": "text/plain; charset=utf-8"}
    if title:
        # ntfy reads Title from a header, so it must survive as ONE line.
        headers["Title"] = title.replace("\n", " ")[:250]
    if tags:
        headers["Tags"] = tags
    token = os.environ.get("NTFY_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    if dry:
        return Result("ntfy", True, f"would POST {url} priority={headers['Priority']} ({len(msg)}B)", dry=True)
    try:
        status, body = _post(url, msg.encode("utf-8"), headers)
    except Exception as e:  # noqa: BLE001
        return Result("ntfy", False, f"{url} unreachable: {e}")
    if 200 <= status < 300:
        try:
            ident = json.loads(body).get("id", "")
        except Exception:  # noqa: BLE001
            ident = ""
        return Result("ntfy", True, f"http {status} {url}" + (f" id={ident}" if ident else ""))
    return Result("ntfy", False, f"http {status} {url}: {body.strip()[:160]}")


def send_webhook(msg: str, title: str, severity: str, dry: bool) -> Result | None:
    """A generic JSON webhook: Slack, Mattermost, Discord, or your own IRC bridge.

    The payload key differs per service (Slack/Mattermost: "text", Discord:
    "content"), so it is configuration, not a guess — NOTIFY_WEBHOOK_KEY.
    """
    url = os.environ.get("NOTIFY_WEBHOOK_URL")
    if not url:
        return None
    key = os.environ.get("NOTIFY_WEBHOOK_KEY", "text")
    text = f"[{severity}] {title}\n{msg}" if title else f"[{severity}] {msg}"
    payload = json.dumps({key: text}).encode("utf-8")
    if dry:
        return Result("webhook", True, f"would POST {url} key={key!r} ({len(payload)}B)", dry=True)
    try:
        status, body = _post(url, payload, {"Content-Type": "application/json"})
    except Exception as e:  # noqa: BLE001
        return Result("webhook", False, f"{url} unreachable: {e}")
    if 200 <= status < 300:
        return Result("webhook", True, f"http {status} {url}")
    return Result("webhook", False, f"http {status} {url}: {body.strip()[:160]}")


def read_message(args: argparse.Namespace) -> str:
    """Body from a file or stdin by preference.

    A message assembled inline in a double-quoted shell string is expanded by
    the shell before this program ever runs — backticks and $(...) in an
    incident report (which quote commands constantly) either EXECUTE or are
    silently deleted, and the remaining sentence usually still reads fine.
    --file and stdin are inert.
    """
    if args.file:
        if args.file == "-":
            return sys.stdin.read()
        with open(args.file, encoding="utf-8") as fh:
            return fh.read()
    if args.message:
        return " ".join(args.message)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="notify", description=__doc__.split("\n")[0])
    p.add_argument("message", nargs="*", help="short body; prefer --file for anything longer")
    p.add_argument("--file", "-f", help="read the body from a file, or - for stdin (preferred)")
    p.add_argument("--title", "-t", default="", help="one-line subject")
    p.add_argument("--severity", "-s", default="info", choices=SEVERITIES)
    p.add_argument("--tags", default="", help="ntfy tags, comma-separated (e.g. warning,disk)")
    p.add_argument("--min-severity", default=os.environ.get("NOTIFY_MIN_SEVERITY", "debug"),
                   choices=SEVERITIES, help="drop anything below this")
    p.add_argument("-n", "--dry-run", action="store_true")
    args = p.parse_args(argv)

    msg = read_message(args).strip()
    if not msg and not args.title:
        print("refusing to send an empty message. Nothing was sent.", file=sys.stderr)
        return UNCONFIG

    if SEVERITIES.index(args.severity) < SEVERITIES.index(args.min_severity):
        print(
            f"suppressed: severity={args.severity} is below NOTIFY_MIN_SEVERITY="
            f"{args.min_severity}. NOTHING WAS SENT.",
            file=sys.stderr,
        )
        return UNCONFIG

    results = [
        r
        for r in (
            send_ntfy(msg, args.title, args.severity, args.tags, args.dry_run),
            send_webhook(msg, args.title, args.severity, args.dry_run),
        )
        if r is not None
    ]

    if not results:
        print(
            "NOTHING WAS SENT — no transport is configured.\n"
            "  Set NTFY_URL + NTFY_TOPIC, and/or NOTIFY_WEBHOOK_URL.\n"
            "  This is exit 3, never 0: an escalation path with no transport behind it\n"
            "  is not a quiet success, it is the outage you find out about tomorrow.",
            file=sys.stderr,
        )
        return UNCONFIG

    for r in results:
        print(r)
    accepted = sum(1 for r in results if r.ok)

    # Flush stdout first, or this note overtakes the per-transport lines it
    # summarises and the transcript reads backwards.
    sys.stdout.flush()
    if args.dry_run:
        print(f"\n{len(results)} transport(s) would be attempted. NOTHING WAS SENT.", file=sys.stderr)
    else:
        print(
            f"\n{accepted}/{len(results)} transport(s) ACCEPTED the message. "
            f"'Accepted' means the server took it — not that a human read it.",
            file=sys.stderr,
        )

    if accepted == len(results):
        return DELIVERED
    if accepted:
        return PARTIAL
    return FAILED


if __name__ == "__main__":
    sys.exit(main())
