"""Pair an existing identity-proven Codex server; never invoke lifecycle commands.

The installed experimental app-server protocol supplies manual codes. Its other
response fields may contain credentials: only explicitly selected fields leave
this module. Nothing here creates directories, logs responses or retries writes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import codex_daemon, harness
from .answer import CouldNotLook, PartialAnswer
from .deployment import local_host


class RemoteError(Exception):
    """A bounded, credential-free diagnostic safe to show to the operator."""


class Inactive(RemoteError):
    """The selected runtime has no control socket; never start one implicitly."""


class Control:
    """Existing daemon only, bound before/after RPC to its recorded generation."""

    def __init__(self, agent, timeout):
        self.agent = agent
        self.deadline = time.monotonic() + timeout
        self.client = None
        self.sequence = 0

    def __enter__(self):
        from .codex_shells import ControlSocket, control_binding, _json
        home = codex_daemon.runtime_home(self.agent)
        try:
            home.stat()
        except FileNotFoundError:
            raise Inactive("no existing runtime home; nothing launched")
        records = [home / "app-server-daemon" / name
                   for name in ("daemon.pid", "app-server.pid")
                   if os.path.lexists(home / "app-server-daemon" / name)]
        if not records:
            raise Inactive("no recorded daemon; nothing launched")
        if len(records) != 1:
            raise RemoteError("ambiguous daemon identity; pairing refused")
        record, _ = _json(records[0])
        pid = record.get("pid")
        if type(pid) is not int or pid <= 0:
            raise RemoteError("invalid recorded daemon identity")
        if not sys.platform.startswith("linux"):
            # No /proc on macOS is not evidence that its recorded PID is dead.
            # Keep the peer/identity requirement instead of weakening it.
            raise RemoteError("native control identity inspection is unsupported on this platform; nothing launched")
        try:
            (Path('/proc') / str(pid)).stat()
        except FileNotFoundError:
            raise Inactive("recorded daemon is not running; nothing launched") from None
        try:
            self.binding = control_binding(self.agent)
            self.client = ControlSocket(self.binding["endpoint"], self.binding["pid"], self.deadline)
            self.rpc("initialize", {"clientInfo": {"name": "shantytown", "version": "1"},
                                    "capabilities": {"experimentalApi": True}})
            self.client.send({"method": "initialized", "params": {}})
            return self
        except BaseException:
            if self.client:
                self.client.close()
            raise

    def __exit__(self, kind, *_):
        from .codex_shells import control_binding
        try:
            if kind is None and control_binding(self.agent) != self.binding:
                raise RemoteError("daemon identity changed; response withheld")
        finally:
            if self.client:
                self.client.close()

    def rpc(self, method, params):
        self.sequence += 1
        try:
            return self.client.request(self.sequence, method, params)
        except ValueError:
            raise RemoteError("unsupported or rejected control response; check daemon version/account; outcome unknown") from None


def _status(control):
    value = control.rpc("remoteControl/status/read", None)
    state = value.get("status")
    host = value.get("serverName")
    if (not isinstance(state, str) or state not in {"disabled", "connecting", "connected", "errored"}
            or not isinstance(host, str) or not host.isprintable() or len(host) > 128):
        raise RemoteError("unrecognized remote-control status")
    return value


def status(control):
    value = _status(control)
    state, host = value["status"], value["serverName"]
    # Environment/installation identifiers never enter discovery output.
    return {"availability": state, "server_name": host[:128]}


def pairing(control, *, now=None):
    before = _status(control)
    if before["status"] != "connected":
        raise RemoteError("remote control is not connected; no enable/start attempted")
    expected = before.get("environmentId")
    if not isinstance(expected, str) or not expected:
        raise RemoteError("daemon environment identity is unknown; pairing refused")
    value = control.rpc("remoteControl/pairing/start", {"manualCode": True})
    if value.get("environmentId") != expected:
        raise RemoteError("pairing environment changed; response withheld")
    code, expiry = value.get("manualPairingCode"), value.get("expiresAt")
    if not isinstance(code, str) or not code or len(code) > 128 or not code.isprintable():
        raise RemoteError("daemon did not return a usable manual code; outcome unknown")
    if type(expiry) is not int or expiry <= (time.time() if now is None else now):
        raise RemoteError("pairing response is expired or invalid; code withheld")
    try:
        expires = datetime.fromtimestamp(expiry, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        raise RemoteError("pairing expiry is outside the supported range") from None
    return {"manual_pairing_code": code, "expires_at": expires}


def prerequisites(card, cards, root):
    """Selected launch prerequisites only; never repair pointers or run Codex."""
    result = {"remote_configured": None, "managed_payload": "unknown",
              "phone_visibility": "unverified"}
    if root is None:
        return result
    try:
        from .cli import _default_settings
        from .account_auth import settings_path
        result["remote_configured"] = harness.CodexHarness._remote_control(root)
        selected = settings_path(card, _default_settings(root, cards)(card), root)
        if selected is None:
            result["managed_payload"] = "settings_missing"
        else:
            # The launcher owns pointer repair. Discovery must leave even a
            # stale pointer alone, so it reports the selected path as-is.
            binary = Path(selected).parent / "packages/standalone/current/codex"
            result["managed_payload"] = ("present" if binary.is_file()
                                         and os.access(binary, os.X_OK) else "missing")
    except (OSError, ValueError, LookupError, harness.Unsupported):
        pass  # Config/provider exceptions may contain private values.
    return result


def describe_names(rows):
    """Local card labels cannot rename the provider's advertised server."""
    counts = {}
    for row in rows:
        if "server_name" in row:
            counts[row["server_name"]] = counts.get(row["server_name"], 0) + 1
    for row in rows:
        row["local_label"] = f"{row['host']}/{row['agent']}" if row["host"] else None
        if "server_name" in row:
            row["duplicate_server_name"] = counts[row["server_name"]] > 1


def run(args, registry, *, control_factory=Control):
    """Discovery is metadata only; pair prints secrets solely on explicit stdout."""
    try:
        if not 0.1 <= args.timeout <= 30:
            raise RemoteError("timeout must be between 0.1 and 30 seconds")
        cards = [registry.get(args.agent)] if args.remote_action == "pair" else registry.all().exact()
        if args.remote_action == "pair" and cards[0].name != args.agent:
            raise RemoteError("registry returned another agent; pairing refused")
        rows = []
        host = local_host(getattr(args, "root", None))
        for card in cards:
            row = {"agent": card.name, "harness": None,
                   "host": card.host or host, "availability": "unavailable"}
            try:
                row["harness"] = harness.name_for(card, root=getattr(args, "root", None))
            except (harness.UnknownHarness, LookupError, OSError, ValueError):
                if args.remote_action == "pair":
                    raise RemoteError("cannot resolve selected card harness; no connection attempted") from None
                row.update(availability="unknown", detail="cannot resolve card harness; no connection attempted")
                rows.append(row)
                continue
            if card.host and card.host != host:
                if args.remote_action == "pair":
                    raise RemoteError("selected card belongs to another or unresolved host; use its configured deployment")
                row["detail"] = "card belongs to another or unresolved host; no connection attempted"
            elif row["harness"] != "codex":
                if args.remote_action == "pair":
                    raise RemoteError("selected card is not a Codex agent")
            else:
                row.update(prerequisites(card, cards, getattr(args, "root", None)))
                try:
                    with control_factory(card.name, args.timeout) as control:
                        row.update(status(control))
                        if args.remote_action == "pair":
                            if getattr(args, "dry_run", False):
                                row["action"] = "would_pair"
                            else:
                                row.update(pairing(control))
                except Inactive as error:
                    if args.remote_action == "pair":
                        raise
                    row.update(availability="inactive", detail=str(error))
                except RemoteError as error:
                    if args.remote_action == "pair":
                        raise
                    row.update(availability="unknown", detail=str(error))
                except TimeoutError:
                    if args.remote_action == "pair":
                        raise RemoteError("request timed out; outcome unknown; no automatic retry") from None
                    row.update(availability="unknown", detail="control request timed out")
                except (OSError, ValueError, UnicodeError):
                    if args.remote_action == "pair":
                        raise RemoteError("control request failed; outcome unknown; no automatic retry") from None
                    row.update(availability="unknown", detail="control request failed")
            rows.append(row)
        describe_names(rows)
        if args.json:
            print(json.dumps(rows[0] if args.remote_action == "pair" else rows))
        else:
            for row in rows:
                print(f"{row['agent']}  {row['harness']}  {row['host']}  {row['availability']}")
                if row["harness"] == "codex":
                    print(f"  Local card: {row['local_label'] or 'host unresolved'}; "
                          f"advertised server: {row.get('server_name', 'unknown')}")
                    if row.get("duplicate_server_name"):
                        print("  Duplicate advertised name in this listing; local labels do not rename phone entries.")
                    print("  Phone visibility: unverified; connected is not a selected-session receipt.")
                    if row.get("remote_configured") is False:
                        print("  Remote Control is configured off; no enable/start attempted.")
                    if row.get("managed_payload") == "missing":
                        print("  Selected managed standalone payload is missing; arrange its reviewed installation before a natural launch.")
                if "manual_pairing_code" in row:
                    print(f"Manual code: {row['manual_pairing_code']}\nExpires: {row['expires_at']} (UTC)")
                    print("Use the selected agent's manual pairing flow. Android/QR compatibility and reconnect are unverified.")
                elif row.get("detail"):
                    print(f"  {row['detail']}")
                elif row.get("action") == "would_pair":
                    print("  Would request a manual code; no pairing request sent.")
        return 0
    except (RemoteError, LookupError, OSError, ValueError, CouldNotLook, PartialAnswer):
        # Provider and registry exceptions can embed raw response/credentials.
        # Only our own controlled diagnostics are safe to expose.
        import sys
        error = sys.exception()
        detail = str(error) if isinstance(error, RemoteError) else "cannot resolve selected card or control connection"
        print(f"remote: {detail}", file=sys.stderr)
        return 2
