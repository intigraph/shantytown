"""Project optional role-owned retrieval preferences into a crew workspace.

Templates live beside the normal provisioning kit. Existing personal config
and edits after projection are refused rather than overwritten. No host-global
config or tracker read belongs here.
"""
import hashlib
import json
from pathlib import Path
import re
import tomllib


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def prepare(root, workspace, role):
    if not isinstance(role, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", role):
        raise ValueError("invalid Bobbin projection role")
    source = Path(root) / "provision" / "bobbin" / (role + ".toml")
    if not source.exists():
        if (Path(workspace) / ".bobbin" / "crew-scope-receipt.json").exists():
            raise ValueError("Bobbin role template missing for previously projected workspace")
        return {}
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 262144:
        raise ValueError("Bobbin role template must be a bounded regular file")
    text = source.read_text()
    parsed = tomllib.loads(text)
    if set(parsed) - {"groups", "hooks"}:
        raise ValueError("Bobbin role template may only declare groups and hooks")
    groups = parsed.get("groups", [])
    if not isinstance(groups, list) or any(not isinstance(g, dict) for g in groups):
        raise ValueError("invalid Bobbin group declarations")
    names = []
    for group in groups:
        if set(group) - {"name", "repos"}:
            raise ValueError("unsupported Bobbin group settings")
        name = group.get("name")
        repos = group.get("repos")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
            raise ValueError("invalid Bobbin group name")
        if not isinstance(repos, list) or any(
            not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", repo)
            for repo in repos
        ):
            raise ValueError("invalid Bobbin group repositories")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("duplicate Bobbin group name")
    hooks = parsed.get("hooks", {})
    if not isinstance(hooks, dict) or set(hooks) - {"search_group", "roles"}:
        raise ValueError("invalid Bobbin hook scope settings")
    roles = hooks.get("roles", {})
    if not isinstance(roles, dict) or any(not isinstance(v, list) for v in roles.values()):
        raise ValueError("invalid Bobbin role group lists")
    selected = [hooks["search_group"]] if "search_group" in hooks else []
    selected += [group for values in roles.values() for group in values]
    if any(not isinstance(name, str) or name not in names for name in selected):
        raise ValueError("Bobbin scope references an unknown group")
    target = Path(workspace) / ".bobbin" / "config.toml"
    receipt = target.with_name("crew-scope-receipt.json")
    rendered = "# Managed crew retrieval scope; source: role provisioning kit.\n" + text
    if target.parent.is_symlink() or target.is_symlink() or receipt.is_symlink():
        raise ValueError("refusing symlink Bobbin projection")
    if target.exists():
        try:
            previous = json.loads(receipt.read_text())["sha256"]
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("existing Bobbin config has no projection receipt") from None
        if _digest(target.read_text()) != previous:
            raise ValueError("Bobbin config changed after projection; preserve personal settings")
    return {target: rendered, receipt: json.dumps({"role": role, "sha256": _digest(rendered)}) + "\n"}
