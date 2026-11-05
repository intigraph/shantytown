"""Positive landing proofs, independent of a feature branch surviving remotely.

Only trusted publication peers supplied by workspace may certify a landing.
Bounded API reads run at explicit fetch/refresh boundaries, never edit-time hooks.
Missing, partial or stale evidence leaves the candidate commits protected.
# arming: library — cycle fetch and existing scheduled tend respawn refresh.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
import urllib.request

SHA = re.compile(r"[0-9a-f]{40}")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
LIMIT = 512


def valid_record(record):
    return (isinstance(record, dict) and type(record.get("number")) is int
            and record["number"] > 0 and isinstance(record.get("head"), str)
            and isinstance(record.get("merge"), str)
            and SHA.fullmatch(record["head"]) and SHA.fullmatch(record["merge"]))


def forge_identity(url):
    """Do not infer credentials or a forge from a local path or arbitrary URL."""
    if re.fullmatch(r"git@[^/:]+:[^:]+", url):
        host, path = url[4:].split(":", 1)
        base = "https://" + host
    else:
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http", "ssh") or not parsed.hostname:
            return None
        if parsed.password or parsed.query or parsed.fragment:
            return None
        host, path = parsed.hostname, parsed.path.lstrip("/")
        base = ("https://" + host if parsed.scheme == "ssh"
                else parsed.scheme + "://" + parsed.netloc)
        if parsed.scheme != "ssh" and parsed.username:
            return None
    path = path.removesuffix(".git")
    if not REPO.fullmatch(path):
        return None
    return base, host, path


class RepositoryRows(list):
    """Rows tied to the configured GitHub endpoint after a verified rename."""
    def __init__(self, rows, repository):
        super().__init__(rows)
        self.repository = repository


def read_merged_prs(url, tip=None):
    """One bounded page. Absence on this page is UNKNOWN, never a negative proof."""
    identity = forge_identity(url)
    if not identity:
        return []
    base, host, repo = identity
    if host == "github.com":
        from .workspace import run_with_group_timeout
        endpoint = (f"repos/{repo}/commits/{tip}/pulls?per_page=50"
                    if isinstance(tip, str) and SHA.fullmatch(tip) else
                    f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=50")
        result = run_with_group_timeout(
            ["gh", "api", endpoint],
            10, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode or len(result.stdout) > 4_000_000:
            return []
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or len(rows) > 50:
            return []
        # GitHub redirects old owner/repo URLs after a rename. Resolve that
        # exact configured endpoint, and bind rows to its immutable repository ID.
        metadata = run_with_group_timeout(
            ["gh", "api", f"repos/{repo}"], 10,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if metadata.returncode or len(metadata.stdout) > 256_000:
            return []
        repository = json.loads(metadata.stdout)
        if not isinstance(repository, dict):
            return []
        name, repo_id = repository.get("full_name"), repository.get("id")
        if not isinstance(name, str) or not REPO.fullmatch(name) or type(repo_id) is not int or repo_id <= 0:
            return []
        verified = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            base = row.get("base")
            owner = base.get("repo") if isinstance(base, dict) else None
            if (isinstance(owner, dict) and type(owner.get("id")) is int
                    and owner["id"] == repo_id and owner.get("full_name") == name):
                verified.append(row)
        return RepositoryRows(verified, name)
    else:
        # Existing Forgejo credential belongs ONLY to its configured origin.
        configured = os.environ.get("SHANTY_FORGEJO_URL", "").rstrip("/")
        configured_url = urlsplit(configured)
        if (configured_url.scheme in ("http", "https") and configured_url.hostname == host
                and not configured_url.username and not configured_url.password):
            base = configured
        headers = {"Accept": "application/json"}
        token = os.environ.get("SHANTY_FORGEJO_TOKEN", "")
        if token and configured == base:
            headers["Authorization"] = "token " + token
        request = urllib.request.Request(
            f"{base}/api/v1/repos/{repo}/pulls?state=closed&sort=recentupdate&limit=50&page=1",
            headers=headers)
        # Do not forward authentication to a redirect destination.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
            data = response.read(4_000_001)
        if len(data) > 4_000_000:
            return []
        rows = json.loads(data)
    return rows if isinstance(rows, list) and len(rows) <= 50 else []


def exact_deltas(output):
    """Parse NUL-delimited raw Git changes, preserving paths and blob/mode IDs.

    Paths are consumed only after metadata; a filename resembling a commit ID
    cannot become a history header. Malformed/truncated output proves nothing.
    """
    if len(output) > 4_000_000 or (output and not output.endswith("\0")):
        return {}
    tokens, result, commit, entries, i = output.split("\0"), {}, None, [], 0
    raw = re.compile(r":[0-7]{6} [0-7]{6} [0-9a-f]{40} [0-9a-f]{40} [ADMT]")
    while i < len(tokens):
        token = tokens[i].lstrip("\n")
        if not token:
            i += 1
            continue
        if SHA.fullmatch(token):
            if commit and entries:
                result[commit] = tuple(entries)
            commit, entries = token, []
            i += 1
        elif commit and raw.fullmatch(token) and i + 1 < len(tokens) and tokens[i + 1]:
            entries.append((token, tokens[i + 1]))
            i += 2
        else:
            return {}
    if commit and entries:
        result[commit] = tuple(entries)
    return result


def main_ref(repo, remote, run):
    code, symbolic = run(repo, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    allowed = [f"refs/remotes/{remote}/main", f"refs/remotes/{remote}/master"]
    candidates = ([symbolic] if code == 0 and symbolic in allowed else []) + allowed
    for ref in candidates:
        if ref and run(repo, "rev-parse", "--verify", ref + "^{commit}")[0] == 0:
            return ref
    return None


class Proofs:
    """Reusable bounded proof context for one successfully refreshed peer."""
    def __init__(self, repo, remote, run, *, network=False, reader=None):
        self.repo, self.remote, self.run = repo, remote, run
        self.base = main_ref(repo, remote, run)
        code, self.base_oid = run(repo, "rev-parse", self.base) if self.base else (1, "")
        if code or not SHA.fullmatch(self.base_oid):
            self.base = None
        self._merged, self._reachable = {}, {}
        self._exact, self._deltas = None, {}
        code, self.url = run(repo, "remote", "get-url", remote)
        self.identity = forge_identity(self.url) if code == 0 else None
        self.records = []
        self.path = None
        if self.identity:
            code, common = run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
            if code == 0 and common:
                self.path = Path(common) / "st-landed" / (hashlib.sha256(self.url.encode()).hexdigest() + ".json")
            cached = {}
            try:
                if self.path and self.path.stat().st_size <= 256_000:
                    cached = json.loads(self.path.read_text())
            except (OSError, ValueError):
                pass
            if not isinstance(cached, dict):
                cached = {}
            if cached.get("remote") == self.url and isinstance(cached.get("records"), list):
                self.records = [r for r in cached["records"][:256] if valid_record(r)]
            checked = cached.get("checked_at", 0)
            if not isinstance(checked, (float, int)) or checked > time.time():
                checked = 0
            if network and time.time() - checked > 60:
                try:
                    rows = (reader or read_merged_prs)(self.url)
                    added = []
                    for row in rows:
                        record = self._record(row, rows.repository if isinstance(rows, RepositoryRows) else None)
                        if record:
                            added.append(record)
                    rc, tip = self.run(repo, "rev-parse", "HEAD")
                    related = any(self.run(repo, "merge-base", "--is-ancestor", tip, r["head"])[0] == 0
                                  or self.run(repo, "merge-base", "--is-ancestor", r["head"], tip)[0] == 0
                                  for r in added + self.records)
                    if (not related and rc == 0 and SHA.fullmatch(tip)
                            and self.identity[1] == "github.com" and reader is None):
                        # One exact-tip association query covers an old PR outside
                        # the recent page; it never turns an absent result into proof.
                        older = read_merged_prs(self.url, tip=tip)
                        for row in older:
                            record = self._record(row, older.repository if isinstance(older, RepositoryRows) else None)
                            if record:
                                added.append(record)
                    seen = set()
                    self.records = [r for r in added + self.records
                                    if valid_record(r)
                                    and not (r["head"] in seen or seen.add(r["head"]))][:256]
                    self._save()
                except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.TimeoutExpired):
                    pass  # Unknown API result does not clear a single commit.

    def _record(self, row, expected_repository=None):
        if not isinstance(row, dict) or row.get("state") != "closed":
            return None
        if not row.get("merged_at") and row.get("merged") is not True:
            return None
        base = row.get("base")
        repository = base.get("repo") if isinstance(base, dict) else None
        name = repository.get("full_name") if isinstance(repository, dict) else None
        if not isinstance(name, str) or name.casefold() != (expected_repository or self.identity[2]).casefold():
            return None
        head_info = row.get("head")
        head = head_info.get("sha") if isinstance(head_info, dict) else None
        merge = row.get("merge_commit_sha", "")
        if not isinstance(head, str) or not isinstance(merge, str):
            return None
        if not SHA.fullmatch(head) or not SHA.fullmatch(merge) or type(row.get("number")) is not int:
            return None
        return {"head": head, "merge": merge, "number": row["number"],
                "branch": head_info.get("ref", "")}

    def _save(self):
        if not self.path:
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        value = {"remote": self.url, "checked_at": time.time(), "records": self.records}
        # Common gitdir, not tracked content. Atomic writes tolerate other worktrees.
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream)
        os.replace(temp, self.path)

    def clear(self, candidates, tip="HEAD"):
        if not self.base:
            return set(), []
        cleared, notes = set(), []
        # Patch IDs (including git cherry) ignore meaningful whitespace. Only
        # identical raw paths, old/new blob IDs and modes certify a replay.
        options = ("--no-merges", "--format=%H", "--raw", "-z", "--no-abbrev", "--no-renames")
        if self._exact is None:
            code, history = self.run(self.repo, "log", f"-n{LIMIT}", *options, self.base_oid)
            self._exact = set(exact_deltas(history).values()) if code == 0 else set()
        for candidate in candidates:
            if not isinstance(candidate, str) or not SHA.fullmatch(candidate):
                continue
            if candidate not in self._deltas:
                code, changes = self.run(self.repo, "log", "-n1", *options, candidate)
                self._deltas[candidate] = exact_deltas(changes).get(candidate) if code == 0 else None
            delta = self._deltas[candidate]
            if delta and delta in self._exact:
                cleared.add(candidate)
        if cleared:
            notes.append(f"{len(cleared)} exact path/blob/mode delta on {self.base}")
        for record in self.records:
            if not isinstance(record, dict):
                continue
            head, merge = record.get("head", ""), record.get("merge", "")
            if not isinstance(head, str) or not isinstance(merge, str):
                continue
            if (not SHA.fullmatch(head) or not SHA.fullmatch(merge)
                    or type(record.get("number")) is not int):
                continue
            if merge not in self._merged:
                self._merged[merge] = self.run(self.repo, "merge-base", "--is-ancestor", merge, self.base_oid)[0] == 0
            if not self._merged[merge]:
                continue
            if head not in self._reachable:
                code, reachable = self.run(self.repo, "rev-list", f"--max-count={LIMIT}",
                                           head, "--not", self.base_oid)
                self._reachable[head] = set(reachable.splitlines()) if code == 0 else set()
            found = (self._reachable[head] & set(candidates)) - cleared
            if found:
                cleared.update(found)
                notes.append(f"{len(found)} reachable from merged PR #{record['number']} head {head[:12]} ({self.remote})")
            if cleared == set(candidates):
                break
        return cleared, notes


def classify(repo, candidates, remotes, run, *, network=False):
    cleared, notes = set(), []
    for remote in remotes:
        proof = Proofs(repo, remote, run, network=network)
        found, why = proof.clear(candidates)
        cleared.update(found)
        notes.extend(why)
    return cleared, notes


def retire_and_prune(repo, remotes, run):
    """Explicit worktree refresh / stopped-agent respawn, after successful fetch.

    Never reset, force, rebase or overwrite dirt. Branch refs are deleted by CAS
    only when unoccupied, upstream-gone and positively landed. Bounded per pass.
    """
    if run(repo, "status", "--porcelain") != (0, ""):
        return None
    code, branch = run(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch in ("main", "master"):
        return None
    if code:
        branch = "(detached)"
    for remote in remotes:
        proof = Proofs(repo, remote, run, network=True)
        if not proof.base:
            continue
        code, head = run(repo, "rev-parse", "HEAD")
        code2, ahead = run(repo, "rev-list", f"{proof.base_oid}..{head}")
        candidates = ahead.splitlines()
        if code or code2 or len(candidates) > LIMIT:
            continue
        # A fresh topic, even one now behind main, has never landed anything.
        # Ordinary ancestry alone cannot distinguish it from a merged topic.
        # With no rewritten commits, require a merged PR for THIS branch.
        if not candidates and branch != "(detached)":
            matched = any(r.get("head") == head and r.get("branch") == branch
                          and run(repo, "merge-base", "--is-ancestor", r["merge"], proof.base_oid)[0] == 0
                          for r in proof.records)
            if not matched:
                continue
        cleared, notes = proof.clear(candidates)
        if set(candidates) != cleared:
            continue
        # Ordinary ancestry is also positive. Recheck HEAD and dirt at mutation.
        if run(repo, "rev-parse", "HEAD") != (0, head) or run(repo, "status", "--porcelain") != (0, ""):
            return None
        if run(repo, "rev-parse", proof.base) != (0, proof.base_oid):
            return None
        if run(repo, "switch", "--detach", proof.base_oid)[0] != 0:
            return None
        removed = []
        code, trees = run(repo, "worktree", "list", "--porcelain")
        code2, refs = run(repo, "for-each-ref", "--format=%(refname)\t%(objectname)\t%(upstream:track)", "refs/heads")
        if code == code2 == 0:
            occupied = {line[7:] for line in trees.splitlines() if line.startswith("branch ")}
            budget = 32
            for line in refs.splitlines():
                fields = line.split("\t")
                if len(fields) != 3:
                    continue
                ref, oid, track = fields
                short = ref.removeprefix("refs/heads/")
                keep_rc, keep = run(repo, "config", "--bool", "--get", f"branch.{short}.st-keep")
                if keep == "true" or keep_rc not in (0, 1):
                    continue
                confirmed_head = any(r.get("head") == oid and r.get("branch") == short and
                                     run(repo, "merge-base", "--is-ancestor", r.get("merge", ""), proof.base_oid)[0] == 0
                                     for r in proof.records if isinstance(r, dict))
                if (ref in occupied or (track != "[gone]" and not confirmed_head)
                        or ref in ("refs/heads/main", "refs/heads/master")):
                    continue
                if budget == 0:
                    break
                budget -= 1
                rc, extra = run(repo, "rev-list", f"{proof.base_oid}..{oid}")
                commits = extra.splitlines()
                if rc or len(commits) > LIMIT or set(commits) != proof.clear(commits, oid)[0]:
                    continue
                rc, current_trees = run(repo, "worktree", "list", "--porcelain")
                if rc or f"branch {ref}" in current_trees.splitlines():
                    continue
                # Retain a recovery ref; compare-and-delete cannot remove a
                # newer unpublished tip on the strength of an older proof.
                recovery = f"refs/st/landed-retained/{oid}"
                rc, saved = run(repo, "rev-parse", "--verify", recovery)
                if rc:
                    if run(repo, "update-ref", recovery, oid, "0" * 40)[0]:
                        continue
                elif saved != oid:
                    continue
                if run(repo, "update-ref", "-d", ref, oid)[0] == 0:
                    removed.append(ref.removeprefix("refs/heads/"))
        return f"landed worktree {branch} detached at {proof.base}; {'; '.join(notes) or 'ancestry proven'}; pruned {len(removed)} landed/gone branch(es)"
    return None
