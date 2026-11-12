"""Run with PYTHONPATH pointing at a base or candidate checkout.

Uses temporary local cards and an explicit graph stub; no live fleet calls.
"""
import json
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace

from shantytown import cli, quipu, stop_event
from shantytown.events import FilesEvents
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent
from shantytown.tmux import NullPanes


with tempfile.TemporaryDirectory(prefix="remote-lead-demo-") as directory:
    root = Path(directory)
    crew = root / "crew"
    crew.mkdir()
    (crew / "worker.json").write_text(json.dumps({
        "role": "worker", "reports_to": "remote-admin", "host": "local"}))
    (crew / "local-admin.json").write_text(json.dumps({"role": "administrator"}))
    (root / "shantytown.toml").write_text(
        '[host]\nname="local"\n[env]\nQUIPU_SERVER="http://graph.example"\n'
        'SHANTY_ONTO_NS="http://crew.example/ontology/"\n')
    def graph_member(self, name):
        if name != "remote-admin":
            raise LookupError(name)
        return Agent(name=name, role="administrator", host="remote")
    quipu.QuipuRegistry.get = graph_member
    cli._panes = lambda a: NullPanes()
    cli._tracker = lambda a: None
    cli._plate = lambda *a, **kw: lambda name: None
    args = SimpleNamespace(root=root, registry="files")
    print("Fixture: local worker, remote administrator, no local lead card; graph stub.")
    try:
        result, _, _ = cli._resolve_anchor(args, "worker")
    except LookupError:
        print("ANCHOR REFUSED: declared lead absent from local cards.")
    else:
        print(f"ANCHOR PASS: reports_to={result.me.reports_to}, lead={result.lead.name}")
    stop_event._my_shells = lambda *a: 0
    stop_event._my_context_k = lambda *a: None
    stop_event._plate_of = lambda *a: (None, None, [])
    relays = []
    stop_event._offhost_durable = lambda r, root, to, *a: relays.append(to)
    events = FilesEvents(root / "events")
    with contextlib.redirect_stderr(io.StringIO()):
        code = stop_event._send(FilesRegistry(crew), events, NullPanes(), "worker", root)
    if code:
        print(f"STOP REFUSED: exit={code}")
    else:
        assert len(events.pending("remote-admin")) == 1
        assert not events.pending("local-admin")
        assert relays == ["remote-admin"]
        print("STOP PASS: queued to remote-admin; durable relay seam selected; local-admin=0")
    assert not (crew / "remote-admin.json").exists()
    print("No local lead card created. Relay transport is stubbed, not delivered.")
