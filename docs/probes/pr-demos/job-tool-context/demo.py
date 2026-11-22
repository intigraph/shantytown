import json, os, subprocess, sys, tempfile, types
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
for name in tuple(os.environ):
    if name.startswith(("SHANTY_", "ST_")) or name in ("QUIPU_SERVER", "QUIPU_HOOK_GROUP"):
        os.environ.pop(name)
from shantytown import config, ephemeral, job_tools, job_context, provision
from shantytown.protocols import Agent
old = types.ModuleType("shantytown.baseline_provision")
old.__package__ = "shantytown"
source = subprocess.run(["git", "show", "b4d5a1fa:shantytown/provision.py"], check=True,
                        capture_output=True, text=True).stdout
exec(compile(source, "baseline_provision.py", "exec"), old.__dict__)
for label, producer in (("BASE b4d5a1fa", old), ("CANDIDATE", provision)):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "root"; root.mkdir()
        ws = Path(directory) / "workspace"; ws.mkdir()
        templates = root / "provision"; templates.mkdir()
        (templates / provision.MCP_TEMPLATE).write_text(json.dumps({"mcpServers": {
            "bobbin": {"type": "http", "url": "https://search.example.invalid/mcp"},
            "gmail": {"type": "http", "url": "https://mail.example.invalid/mcp"}}}))
        spec = job_tools.validate_specs({"task": {"mcp_servers": ["bobbin"]}}, ephemeral.JOBS)
        rec = {"name": "eph-task-a1b2c3", "job": "task", "state": ephemeral.LAUNCHING,
               "harness": "claude", "workspace": str(ws),
               "jobspec": job_tools.bind(config.Ephemeral(jobs=spec), "task")}
        ephemeral.write(root, rec)
        card = Agent(name=rec["name"], role="worker", harness="claude", workspace=str(ws))
        print(label, "effective workspace MCP servers:", producer.provision(card, root))
        base = root / "role.settings.json"; base.write_text("{}")
        if label == "CANDIDATE":
            selected = job_tools.prepare_settings(root, card, str(base))
            print("  account connectors disabled:", json.loads(Path(selected).read_text())["disableClaudeAiConnectors"])
            try:
                job_tools.filter_servers({}, spec["task"])
            except ValueError:
                print("  missing selected server: REFUSED")
def fail(*args): raise TimeoutError()
os.environ["QUIPU_SERVER"] = "https://graph.example.invalid"
os.environ["SHANTY_ONTO_NS"] = "https://example.invalid/ontology/"
snapshot = job_context.collect(None, "fixture-item", ask=fail)
print("Graph read failure:", snapshot["state"], "(job launch is not blocked)")
