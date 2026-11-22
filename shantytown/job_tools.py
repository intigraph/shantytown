"""Job-owned tool profiles; an absent JobSpec preserves the crew-compatible rail."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
from dataclasses import replace

_FIELDS = {"mcp_servers", "skills", "claude_ai_connectors", "mcp_tools"}
_RESERVED = {"budget", "model", "harness", "verdict", "trigger", "action", "actions",
             "prompt_template", "max_tool_calls"}
_NAME = re.compile(r"[A-Za-z0-9_-]+")


def _names(value, field):
    if (not isinstance(value, list) or len(value) > 64
            or any(not isinstance(x, str) or not _NAME.fullmatch(x) for x in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{field} must be a bounded list of unique names")
    return list(value)


def validate_specs(value, jobs):
    if not isinstance(value, dict) or set(value) - set(jobs):
        raise ValueError("ephemeral.jobs must name only supported job types")
    result = {}
    for name, raw in value.items():
        if not isinstance(raw, dict):
            raise ValueError(f"ephemeral.jobs.{name} must be a table")
        if set(raw) & _RESERVED:
            raise ValueError("reserved JobSpec fields are not implemented yet")
        if set(raw) - _FIELDS:
            raise ValueError("unknown JobSpec field")
        spec = {key: _names(raw.get(key, []), key) for key in ("mcp_servers", "skills")}
        connectors = raw.get("claude_ai_connectors", False)
        if type(connectors) is not bool:
            raise ValueError("claude_ai_connectors must be a boolean")
        spec["claude_ai_connectors"] = connectors
        tools = raw.get("mcp_tools", {})
        if not isinstance(tools, dict) or set(tools) - set(spec["mcp_servers"]):
            raise ValueError("mcp_tools must select only allowed servers")
        spec["mcp_tools"] = {server: _names(names, "mcp_tools") for server, names in tools.items()}
        result[name] = spec
    return result


def bind(policy, job):
    spec = getattr(policy, "jobs", {}).get(job)
    if spec is None:
        return None
    resolved = json.loads(json.dumps(spec))
    digest = hashlib.sha256(json.dumps(resolved, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"resolved": resolved, "sha256": digest}


def selected(root, name):
    from . import ephemeral as eph
    if not root or not eph.is_ephemeral_name(name):
        return None
    rec = eph.read(root, name)
    if not rec or rec.get("jobspec") is None:
        return None
    bound = rec["jobspec"]
    if not isinstance(bound, dict):
        raise ValueError("job tool profile is malformed")
    spec = bound.get("resolved")
    if not isinstance(spec, dict):
        raise ValueError("job tool profile is malformed")
    parsed = validate_specs({rec["job"]: spec}, eph.JOBS)[rec["job"]]
    digest = hashlib.sha256(json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != bound.get("sha256"):
        raise ValueError("job tool profile hash mismatch")
    return parsed


def filter_servers(servers, spec):
    if spec is None:
        return dict(servers)
    missing = set(spec["mcp_servers"]) - set(servers)
    if missing:
        raise ValueError("JobSpec MCP servers are not provisioned: " + ", ".join(sorted(missing)))
    chosen = {name: servers[name] for name in spec["mcp_servers"]}
    from urllib.parse import urlparse
    anonymous = anonymous_read_servers(chosen, spec)
    for name, server in chosen.items():
        host = (urlparse(server.get("url", "")).hostname or "").lower()
        if (name.lower().startswith("quipu") or host.split(".")[0].startswith("quipu")) and name not in anonymous:
            raise ValueError("job Quipu tools require an explicit anonymous read-only profile")
    return chosen


def filter_manifest(manifest, spec):
    if spec is None:
        return manifest
    missing = set(spec["skills"]) - set(manifest.skills)
    if missing:
        raise ValueError("JobSpec skills are not provisioned: " + ", ".join(sorted(missing)))
    return replace(manifest, mcp=filter_servers(manifest.mcp, spec),
                   skills={name: manifest.skills[name] for name in spec["skills"]})


def settings_target(root, card):
    base = Path(root) / "settings"
    return (base / "codex" / f"agent-{card.name}" / "config.toml" if card.harness == "codex"
            else base / f"{card.name}.job.settings.json")


def prepare_settings(root, card, base):
    spec = selected(root, card.name)
    if spec is None:
        return base
    if card.harness not in ("claude", "codex"):
        raise ValueError("job tool profile is not supported by this harness")
    from . import codex
    source = Path(base).read_text()
    if card.harness == "codex":
        data = tomllib.loads(source)
        data["mcp_servers"] = filter_servers(data.get("mcp_servers", {}), spec)
        for name, tools in spec["mcp_tools"].items():
            data["mcp_servers"][name] = dict(data["mcp_servers"][name], enabled_tools=tools)
        body = codex.dumps(data)
    else:
        data = json.loads(source)
        data["disableClaudeAiConnectors"] = not spec["claude_ai_connectors"]
        data["allowedMcpServers"] = [{"serverName": name} for name in spec["mcp_servers"]]
        # Exact allow rules are supplementary to the selected servers and their
        # native read-scoped credentials; they grant no new server authority.
        permissions = data.setdefault("permissions", {})
        permissions["allow"] = [rule for rule in permissions.get("allow", [])
                                if not str(rule).startswith("mcp__")] + [
            f"mcp__{server}__{tool}" for server, tools in spec["mcp_tools"].items() for tool in tools]
        import shlex
        import sys
        command = shlex.join([sys.executable, "-m", "shantytown.job_tools", "--root", str(root),
                              "--job", card.name])
        hooks = data.setdefault("hooks", {})
        hooks.setdefault("PreToolUse", []).append({"matcher": "mcp__.*", "hooks": [
            {"type": "command", "command": command, "timeout": 5}]})
        body = json.dumps(data, sort_keys=True, indent=2) + "\n"
    target = settings_target(root, card)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError("job settings must not alias another settings artifact")
    with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as out:
        temporary = Path(out.name)
        try:
            out.write(body)
            out.close()
            os.chmod(temporary, 0o600)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    if card.harness == "codex":
        from .harness import for_card
        for_card(card, root).provision(str(target), root, workspaces=(card.workspace,))
    return str(target)


def selected_settings(root, card, base):
    if selected(root, card.name) is None:
        return base
    target = settings_target(root, card)
    return str(target) if target.is_file() else base


def prune_skills(workspace, spec):
    if spec is None:
        return
    ws = Path(workspace)
    for runtime in (".claude", ".agents"):
        directory = ws / runtime / "skills"
        if directory.is_symlink():
            raise ValueError("job skill directory must not be a symlink")
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.name in spec["skills"]:
                continue
            if not path.is_symlink():
                raise ValueError("unselected workspace skill is not a provisioned link")
            path.unlink()
    for name in spec["skills"]:
        if not (ws / ".claude" / "skills" / name / "SKILL.md").is_file():
            raise ValueError("selected job skill is not provisioned: " + name)


QUIPU_READ_TOOLS = {"quipu_query", "quipu_ask", "quipu_search", "quipu_graph_list"}


def anonymous_read_servers(servers, spec):
    """Explicit native Quipu reads need no bearer; never relax the crew rail.

    Operators must qualify the endpoint's anonymous-read/write-refusal policy.
    A writer tool, token field, helper, or stdio process is not this profile.
    """
    if spec is None:
        return set()
    approved = set()
    for name, tools in spec["mcp_tools"].items():
        server = servers.get(name, {})
        fields = {str(k).lower(): v for k, v in server.get("headers", {}).items()}
        if (tools and set(tools) <= QUIPU_READ_TOOLS and server.get("url")
                and not server.get("command") and not fields.get("authorization")
                and not any(server.get(k) for k in ("headersHelper", "http_headers_helper",
                                                    "bearer_token", "bearer_token_env_var"))
                and not any(str(k).lower() == "authorization" for k in server.get("http_headers", {}))):
            approved.add(name)
    return approved


def tool_decision(root, name, payload):
    """Claude's per-tool guard denies outside the bound subset; never grants."""
    tool = payload.get("tool_name", "") if isinstance(payload, dict) else ""
    if tool and not tool.startswith("mcp__"):
        return {}
    allowed = False
    try:
        spec = selected(root, name)
        if spec is not None:
            for server in spec["mcp_servers"]:
                prefix = f"mcp__{server}__"
                if tool.startswith(prefix):
                    suffix = tool[len(prefix):]
                    allowed = bool(suffix) and (server not in spec["mcp_tools"]
                                                 or suffix in spec["mcp_tools"][server])
                    break
    except (OSError, ValueError, TypeError, KeyError):
        pass
    if allowed:
        return {}  # other hooks and ordinary permission rules still apply
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "MCP tool is outside this job's verified tool profile."}}


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.read(65537)
        payload = json.loads(raw) if len(raw) <= 65536 else None
    except (ValueError, OSError):
        payload = None
    print(json.dumps(tool_decision(args.root, args.job, payload)))


if __name__ == "__main__":
    main()
