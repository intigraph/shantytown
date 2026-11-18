"""Read-only CLI projection fixture; run with the desired source on PYTHONPATH."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from shantytown import cli, tooling
from shantytown.answer import Answer
from shantytown.files import FilesRegistry
from shantytown.protocols import Agent


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "crew").mkdir()
    ws = root / "workspace"
    ws.mkdir()
    (root / "shantytown.toml").write_text(
        '[host]\nname="local"\n[env]\nSHANTY_TOOLING_MANIFEST="urn:demo:tools"\n')
    (ws / "CLAUDE.md").write_text("Keep local guidance.\n")
    (ws / "AGENTS.md").symlink_to("CLAUDE.md")
    FilesRegistry(root / "crew").set(Agent("ada", workspace=str(ws)))
    manifest = {"version": 1, "mcpServers": {}, "skills": {},
                "instructions": "Use canonical tools."}
    before = (ws / "CLAUDE.md").read_bytes()
    output = io.StringIO()
    with patch.object(tooling.QuipuRegistry, "_query_answer", return_value=
                      Answer.complete_read([{"value": json.dumps(manifest)}], how="demo")), \
            contextlib.redirect_stdout(output):
        code = cli.main(["--root", str(root), "ops", "provision",
                         "--instruction-report", "ada"])
    receipt = json.loads(output.getvalue())
    print("$ st ops provision --instruction-report ada")
    print(json.dumps({"exit": code, "agents": receipt["agents"]}, indent=2))
    print("Instruction bytes unchanged:", before == (ws / "CLAUDE.md").read_bytes())
    print("AGENTS symlink retained:", (ws / "AGENTS.md").is_symlink())
    print("No MCP artifact:", not (ws / ".mcp.json").exists())
