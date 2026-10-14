#!/usr/bin/env python3
"""file_improvement.py — file one improvement issue, backend-pluggable.

The retro hook (retro_hook.py) prompts the MODEL to file improvement issues. This
is the small helper it can call so the same retro works whether or not a tracker
is installed. Same shape as dispatch-work's create backends: the tool does NOT
know what a bead / issue / file is — it needs exactly create(title, body) -> id.

Backends (pick with RETRO_BACKEND, or --backend; default auto):
    beads   ->  bd create            (RETRO_BEADS_REPO -> bd -C, else BEADS_DB)
    gh      ->  gh issue create       (RETRO_GH_REPO, honours GH_HOST for any forge)
    file    ->  append a markdown backlog file   (RETRO_BACKLOG_DIR, default ./retro)
    cmd     ->  RETRO_CREATE_CMD template, must print the new id (e.g. jira)

`auto` degrades gracefully: use beads if `bd` is on PATH, else gh if `gh` is, else
file. So an agent with no tracker still captures the retro as markdown rather than
losing it — a filed idea beats a good idea that evaporated at session end.

Usage:
    file_improvement.py "Cache the graph schema so it isn't re-fetched per run" \\
        --body "What slowed me down: re-fetched schema 6x.\\nProposed fix: cache 1h.\\nWhere: graph client."
    echo "$BODY" | file_improvement.py "Title here" --backend file

Stdlib only. Exit 0 = filed (prints the id/path); non-zero = not filed (says why).
"""

import argparse
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys


def _run(cmd, shell=False):
    return subprocess.run(cmd, capture_output=True, text=True, shell=shell)


def create_beads(title: str, body: str) -> str:
    repo = os.environ.get("RETRO_BEADS_REPO") or os.environ.get("BEADS_DB")
    cmd = ["bd"] + (["-C", repo] if repo else []) + ["create", title]
    if body:
        cmd += ["-d", body]
    r = _run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"bd create failed: {r.stderr.strip()[:160]}")
    m = re.search(r"\b([a-z][a-z0-9_]*-[a-z0-9]+)\b", r.stdout)
    if not m:
        raise RuntimeError(f"bd create gave no id: {r.stdout.strip()[:160]}")
    return m.group(1)


def create_gh(title: str, body: str) -> str:
    # Public GitHub OR any GitHub-compatible forge via GH_HOST. Point RETRO_GH_REPO
    # at your repo; do not assume a particular host.
    repo = os.environ.get("RETRO_GH_REPO")
    cmd = ["gh", "issue", "create", "--title", title, "--body", body or ""]
    if repo:
        cmd += ["--repo", repo]
    r = _run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"gh issue create failed: {r.stderr.strip()[:160]}")
    m = re.search(r"/issues/(\d+)", r.stdout)
    if not m:
        raise RuntimeError(f"gh issue create gave no number: {r.stdout.strip()[:160]}")
    return f"#{m.group(1)}"


def create_file(title: str, body: str) -> str:
    root = pathlib.Path(os.environ.get("RETRO_BACKLOG_DIR", "./retro"))
    root.mkdir(parents=True, exist_ok=True)
    slug = hashlib.sha1(title.encode()).hexdigest()[:8]
    path = root / f"{slug}.md"
    path.write_text(f"# {title}\n\n{body}\n" if body else f"# {title}\n")
    return str(path)


def create_cmd(title: str, body: str, template: str) -> str:
    # Escape hatch for any tracker. Template may reference {title} and {body};
    # it must print the new id (last whitespace token of stdout is taken as id).
    filled = template.replace("{title}", title).replace("{body}", body)
    r = _run(filled, shell=True)
    if r.returncode != 0:
        raise RuntimeError(f"create-cmd failed: {r.stderr.strip()[:160]}")
    toks = r.stdout.split()
    if not toks:
        raise RuntimeError("create-cmd printed no id")
    return toks[-1]


BACKENDS = {"beads": create_beads, "gh": create_gh, "file": create_file}


def _auto() -> str:
    if os.environ.get("RETRO_CREATE_CMD"):
        return "cmd"
    if shutil.which("bd"):
        return "beads"
    if shutil.which("gh"):
        return "gh"
    return "file"


def main() -> int:
    ap = argparse.ArgumentParser(description="File one improvement issue.")
    ap.add_argument("title")
    ap.add_argument("--body", default=None, help="issue body; if omitted, read stdin")
    ap.add_argument(
        "--backend",
        choices=["auto", "cmd", *sorted(BACKENDS)],
        default=os.environ.get("RETRO_BACKEND", "auto"),
    )
    args = ap.parse_args()

    body = args.body
    if body is None:
        body = sys.stdin.read() if not sys.stdin.isatty() else ""

    backend = args.backend if args.backend != "auto" else _auto()
    try:
        if backend == "cmd":
            tmpl = os.environ.get("RETRO_CREATE_CMD")
            if not tmpl:
                raise RuntimeError("backend=cmd but RETRO_CREATE_CMD is unset")
            item = create_cmd(args.title, body, tmpl)
        else:
            item = BACKENDS[backend](args.title, body)
    except Exception as e:  # not filed — say why, non-zero exit
        print(f"NOT FILED ({backend}): {e}", file=sys.stderr)
        return 1
    print(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
