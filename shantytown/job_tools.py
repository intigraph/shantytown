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

_FIELDS = {"mcp_servers", "skills", "claude_ai_connectors", "mcp_tools", "verdicts"}
# Review and merge gates key on these exact names (approve/request-changes sign a
# GateApproval, merged ends the queue), so those jobs may narrow but never rename.
LEGACY_VERDICTS = ("approve", "request-changes", "merged", "blocked", "done", "failed")
_GATED_JOBS = {"review", "merge"}
_RESERVED = {"budget", "model", "harness", "verdict", "trigger", "action", "actions",
             "prompt_template", "max_tool_calls"}
_NAME = re.compile(r"[A-Za-z0-9_-]+")


def _names(value, field):
    if (not isinstance(value, list) or len(value) > 64
            or any(not isinstance(x, str) or not _NAME.fullmatch(x) for x in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{field} must be a bounded list of unique names")
    return list(value)


def validate_job_servers(value):
    """[ephemeral.job_servers.<name>]: job-only MCP definitions.

    Crew provisioning never renders these; a job receives one only when its
    profile selects it, copied into the bound JobSpec (and so into its hash).
    Each must qualify as an anonymous read endpoint at use (see
    anonymous_read_servers); a credential-bearing shape cannot be declared here.
    """
    if not isinstance(value, dict):
        raise ValueError("ephemeral.job_servers must be a table of server tables")
    result = {}
    for name, server in value.items():
        if not _NAME.fullmatch(str(name)) or not isinstance(server, dict):
            raise ValueError("ephemeral.job_servers entries must be named tables")
        result[name] = json.loads(json.dumps(server))
    return result


def validate_specs(value, jobs, job_servers=None, *, resolved=False):
    if not isinstance(value, dict) or set(value) - set(jobs):
        raise ValueError("ephemeral.jobs must name only supported job types")
    job_servers = job_servers or {}
    result = {}
    for name, raw in value.items():
        if not isinstance(raw, dict):
            raise ValueError(f"ephemeral.jobs.{name} must be a table")
        if set(raw) & _RESERVED:
            raise ValueError("reserved JobSpec fields are not implemented yet")
        # server_defs is st's own binding output, never operator input.
        if set(raw) - _FIELDS - ({"server_defs"} if resolved else set()):
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
        if "verdicts" in raw:
            # Absent keeps the legacy enum (and the existing binding hash).
            verdicts = _names(raw["verdicts"], "verdicts")
            if not 1 <= len(verdicts) <= 16 or "blocked" not in verdicts:
                raise ValueError("verdicts must list 1-16 names including blocked")
            if "failed" in verdicts:
                raise ValueError("failed is recorded by st at teardown, not reported by a job")
            if name in _GATED_JOBS and set(verdicts) - set(LEGACY_VERDICTS):
                raise ValueError(f"{name} verdicts may only narrow the gated legacy names")
            spec["verdicts"] = verdicts
        defs = (raw.get("server_defs", {}) if resolved else
                {n: job_servers[n] for n in spec["mcp_servers"] if n in job_servers})
        if not isinstance(defs, dict) or set(defs) - set(spec["mcp_servers"]):
            raise ValueError("job server definitions must be selected servers")
        if defs:
            if set(defs) - anonymous_read_servers(defs, spec):
                raise ValueError("job-only servers must be anonymous read-only Quipu profiles "
                                 "with an explicit mcp_tools read subset")
            spec["server_defs"] = json.loads(json.dumps(defs))
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
    parsed = validate_specs({rec["job"]: spec}, eph.JOBS, resolved=True)[rec["job"]]
    digest = hashlib.sha256(json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != bound.get("sha256"):
        raise ValueError("job tool profile hash mismatch")
    return parsed


_ADMITTED_FIELDS = {"url", "type", "headers", "http_headers", "enabled_tools",
                    "disabled_tools", "enabled", "startup_timeout_sec", "tool_timeout_sec"}


def _admitted_headers(server):
    merged = {}
    for key in ("headers", "http_headers"):
        fields = server.get(key, {})
        if not isinstance(fields, dict):
            return None
        merged.update({str(k).lower(): v for k, v in fields.items()})
    return merged


def _same_admitted_server(present, admitted):
    """True only for the job's own admitted definition after a prior pass.

    Harness rendering may rename headers -> http_headers and add inert
    transport controls; it never changes the endpoint or adds a credential
    field, helper or process, so those still refuse as a crew shadow.
    """
    if not isinstance(present, dict) or set(present) - _ADMITTED_FIELDS:
        return False
    if present.get("url") != admitted.get("url"):
        return False
    headers = _admitted_headers(present)
    return headers is not None and headers == _admitted_headers(admitted)


def filter_servers(servers, spec):
    if spec is None:
        return dict(servers)
    defs = spec.get("server_defs", {})
    # A second pass over an already-filtered kit (provision renders the filtered
    # manifest; Codex launch refilters the job-owned config) carries the job's
    # own admitted definition, not a crew server. Only that exact anonymous
    # endpoint passes; any other same-name server is a genuine shadow.
    shadowed = sorted(name for name in set(defs) & set(servers)
                      if not _same_admitted_server(servers[name], defs[name]))
    if shadowed:
        raise ValueError("job-only server names must not shadow crew servers: "
                         + ", ".join(shadowed))
    servers = {**servers, **defs}
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
    if card.harness == "codex":
        return base / "codex" / f"agent-{card.name}" / "config.toml"
    if card.harness == "agy":
        # agy keeps a native launch-settings.json beside its canonical file, so
        # each job gets its own directory rather than sharing settings/.
        return base / "agy" / f"job-{card.name}" / "settings.json"
    if card.harness == "opencode":
        return base / "opencode" / f"job-{card.name}" / "opencode.json"
    return base / f"{card.name}.job.settings.json"


def _gate_hook(root, card):
    import shlex
    import sys
    command = shlex.join([sys.executable, "-m", "shantytown.job_tools", "--root", str(root),
                          "--job", card.name])
    return {"matcher": "mcp__.*", "hooks": [{"type": "command", "command": command, "timeout": 5}]}


def _ambient_opencode_mcp(card):
    """OpenCode merges global and project config into OPENCODE_CONFIG. The bridge
    names only servers it was told about as mcp__<server>__<tool>; a server from
    any other config would keep a raw tool name the gate never matches. So an
    MCP declaration anywhere else refuses (a false positive refuses, never opens)."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    places = [config_home / "opencode"]
    if card.workspace:
        places += [Path(card.workspace), Path(card.workspace) / ".opencode"]
    found = []
    for place in places:
        for name in ("opencode.json", "opencode.jsonc", "config.json"):
            path = place / name
            try:
                if path.is_file() and '"mcp"' in path.read_text():
                    found.append(str(path))
            except OSError:
                found.append(str(path))
    return found


def prepare_settings(root, card, base):
    spec = selected(root, card.name)
    if spec is None:
        return base
    # agy takes the Claude-shaped canonical file: its hook adapter (agy_hooks)
    # runs these PreToolUse hooks on every call_mcp_tool, translated to
    # mcp__<server>__<tool>, and denies on any refusal or adapter error. Its
    # server set is the workspace kit, which provisioning filters by this same
    # profile. OpenCode's bridge plugin runs the hooks in its own options and
    # throws (refusing the tool) on a deny or any hook failure.
    if card.harness not in ("claude", "codex", "agy", "opencode"):
        raise ValueError("job tool profile is not supported by this harness")
    from . import codex
    source = Path(base).read_text()
    if card.harness == "opencode":
        from .opencode import PLUGIN_NAME
        if (ambient := _ambient_opencode_mcp(card)):
            raise ValueError("OpenCode MCP is declared outside the job config: " + ", ".join(ambient))
        data = json.loads(source)
        # The kit comes from the workspace .mcp.json that provisioning wrote for
        # THIS job (already narrowed to the profile, credentials projected), never
        # from the shared role file, which holds no kit (aegis-j550, measured on
        # vati: every opencode job refused "not provisioned"). The pre-flight
        # compose runs before provisioning, so no kit yet means an empty kit;
        # the launch compose runs after it and must find every selected server.
        data["mcp"] = {}
        kit = Path(card.workspace) / ".mcp.json" if card.workspace else None
        if kit is not None and (kit.is_symlink() or kit.exists()):
            from .opencode import translate_servers
            from .provision import ProvisionError
            if kit.is_symlink() or not kit.is_file():
                raise ValueError("workspace .mcp.json is not a regular file")
            servers = json.loads(kit.read_text()).get("mcpServers", {})
            missing = set(spec["mcp_servers"]) - set(servers)
            if missing:
                raise ValueError("JobSpec MCP servers are not provisioned: " + ", ".join(sorted(missing)))
            try:
                data["mcp"] = translate_servers(
                    {"mcpServers": {name: servers[name] for name in spec["mcp_servers"]}})
            except ProvisionError as exc:
                raise ValueError(str(exc)) from None
        bridges = [p for p in data.get("plugin", []) if isinstance(p, list) and len(p) == 2
                   and str(p[0]).endswith(PLUGIN_NAME) and isinstance(p[1], dict)]
        if len(bridges) != 1:
            raise ValueError("OpenCode job config needs exactly one shantytown bridge")
        options = bridges[0][1]
        options["mcp_servers"] = sorted(data["mcp"])
        options.setdefault("hooks", {}).setdefault("PreToolUse", []).append(_gate_hook(root, card))
        body = json.dumps(data, indent=2) + "\n"
    elif card.harness == "codex":
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
        hooks = data.setdefault("hooks", {})
        hooks.setdefault("PreToolUse", []).append(_gate_hook(root, card))
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
    if card.harness == "agy":
        # Point the workspace hook projection and the native launch file at this
        # job-owned canonical file; agy's SessionStart refuses a mismatch.
        if not card.workspace:
            raise ValueError("agy job tool profile requires the job workspace")
        from .harness import for_card
        for_card(card, root).provision(str(target), root, workspaces=(card.workspace,))
    if card.harness == "codex":
        # The job-owned config makes its directory the job's CODEX_HOME, so
        # the attended exec-policy rules st wrote at spawn (the exact per-PR
        # gh reads and the guarded report) must live there too, or every gh
        # read waits on an approval prompt nobody answers (za4f.2 probe
        # eph-review-4f9d3e). Only a job whose spawn recorded rules gets them;
        # this adds no permission beyond that same allowlist.
        from . import ephemeral as eph
        rec = eph.read(root, card.name)
        if rec and rec.get("codex_rules"):
            eph.write_codex_job_rules(rec, target.parent, unattended=False)
        from .harness import for_card
        for_card(card, root).provision(str(target), root, workspaces=(card.workspace,))
    return str(target)


def selected_settings(root, card, base):
    if selected(root, card.name) is None:
        return base
    target = settings_target(root, card)
    return str(target) if target.is_file() else base


def _hide_tracked_skill(ws, path):
    """Hide a skill the repository itself tracks (za4f.2 camayoc probe).

    Only a directory whose every file is committed and unmodified qualifies:
    it is repository content, not personal state, so removing it from this
    job worktree loses nothing. The paths are marked skip-worktree first, so
    the deletion is invisible to status/add/commit and cannot be published
    by the job. An untracked, modified or ignored file keeps the refusal.
    """
    import shutil
    import subprocess
    rel = str(path.relative_to(ws))
    def git(*args):
        return subprocess.run(["git", "-C", str(ws), *args], capture_output=True,
                              text=True, timeout=30)
    listed = git("ls-files", "-z", "--", rel)
    files = [f for f in listed.stdout.split("\0") if f]
    if listed.returncode or not files:
        return False
    status = git("status", "--porcelain", "--ignored", "--untracked-files=all", "--", rel)
    if status.returncode or status.stdout.strip():
        return False
    on_disk = {str(f.relative_to(ws)) for f in path.rglob("*") if f.is_file() or f.is_symlink()}
    if on_disk - set(files):
        return False
    if git("update-index", "--skip-worktree", "--", *files).returncode:
        return False
    shutil.rmtree(path)
    return True


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
            if path.is_symlink():
                path.unlink()
            elif _hide_tracked_skill(ws, path):
                continue
            else:
                raise ValueError("unselected workspace skill is not a provisioned link")
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
        from urllib.parse import urlparse
        url = server.get("url", "")
        try:
            endpoint = urlparse(url)
            url_safe = (isinstance(url, str) and "$" not in url
                        and endpoint.scheme in {"http", "https"} and bool(endpoint.hostname)
                        and not any((endpoint.username, endpoint.password, endpoint.query, endpoint.fragment)))
        except (TypeError, ValueError, AttributeError):
            url_safe = False
        # This is an anonymous endpoint, not an extensible credential transport.
        # Unknown options (including env-backed headers/auth) cannot silently
        # flow into a native harness config. Only inert transport controls and
        # a narrow set of noncredential headers belong on this rail.
        safe_fields = {"url", "type", "headers", "http_headers", "enabled_tools",
                       "disabled_tools", "enabled", "startup_timeout_sec", "tool_timeout_sec"}
        safe_headers = {"accept", "content-type", "x-quipu-client"}
        header_maps = [server.get(key, {}) for key in ("headers", "http_headers")]
        headers_safe = all(isinstance(fields, dict) and
                           all(str(key).lower() in safe_headers and isinstance(value, str)
                               and "$" not in value for key, value in fields.items())
                           for fields in header_maps)
        if (tools and set(tools) <= QUIPU_READ_TOOLS and url_safe
                and not set(server) - safe_fields and headers_safe):
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
