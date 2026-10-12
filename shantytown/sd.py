"""sd — the seeds tracker backend (aegis-w3k75d.15).

seeds speaks br's verbs and JSON closely enough that BrTracker's methods work
unchanged once the transport is `sd`, with two exceptions this module owns:

1. WHICH STORE. sd ignores `.beads`: run from a br repo it falls back to a
   DEFAULT local store (`.seeds/seeds.db`, prefix `sd`) and answers every read
   with an EMPTY board at exit 0. That is the silent blank plate this repo
   exists to refuse. So SdTracker names its store explicitly on every call
   (`--store <path>` or `--quipu <url>`) and, before its first command, proves
   with `sd where --json` that sd resolved exactly that store. Unproven means
   REFUSE, naming the store, never "an empty board".
2. `comments <id>`: br lists comments with the bare form; sd needs
   `comments list <id>`.

Exact ids: an unknown id exits nonzero in sd (`no seed with id ...`, rc 3), and
SdTracker passes ids through untouched, so nothing fuzzy-resolves.

Selected by SHANTY_BACKEND=seeds (opt-in). Configuration, from the deployment
env like the other SHANTY_* keys:
  SHANTY_SD_STORE  path to a local seeds store, or
  SHANTY_SD_QUIPU  base URL of the quipu server holding the board
  SHANTY_SD_PREFIX the board's id prefix (e.g. aegis). REQUIRED: a fresh or
                   wrong store reports sd's default prefix, so this is what
                   catches a mistyped store in quipu mode
  SHANTY_SD_BIN    the sd binary (default: sd)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from .br import BrTracker, _failure_reason
from .query_identity import sdk_subprocess_options
from .answer import Answer
from .protocols import WorkItem
from .inbox import MESSAGE_PREFIXES, is_message, is_unworkable

#: Backends served by a br-compatible CLI. A site that asks "is this a tracker
#: with plates, comments and hauls" asks THIS, so a new name cannot be missed in
#: one place and silently fall through to files in another.
BR_LIKE = ("beads", "br", "seeds")


class StoreUnproven(RuntimeError):
    """sd could not be shown to read the configured store."""


@dataclass(frozen=True)
class StoreProof:
    """What `sd where --json` showed for the configured store. Only ever built
    from a check that PASSED; a failed check raises StoreUnproven instead."""

    location_source: str
    database_path: "str | None"
    quipu_url: "str | None"
    prefix: "str | None"
    graph: "str | None" = None


class SdTracker(BrTracker):
    """BrTracker over `sd`, pinned to one proven store."""

    _tool = "sd"

    def __init__(self, repo: "str | None" = None, timeout: int = 30, *,
                 store: "str | None" = None, quipu: "str | None" = None,
                 prefix: "str | None" = None):
        # One store, no fan-out: extra br repos are br stores, not seeds.
        super().__init__(repo=repo, timeout=timeout, extra_repos=None)
        self.store = store or None
        self.quipu = quipu or None
        self.prefix = prefix or None
        self._proof: "StoreProof | None" = None
        self._plate_projection_candidates: dict[str, list[dict]] = {}
        self._native_projection: bool | None = None

    @property
    def _bin(self) -> str:
        return os.environ.get("SHANTY_SD_BIN", "sd")

    def _location(self) -> list[str]:
        if self.store and self.quipu:
            raise StoreUnproven(
                "seeds backend: both SHANTY_SD_STORE and SHANTY_SD_QUIPU are set; "
                "name exactly one store")
        if self.store:
            return ["--store", self.store]
        if self.quipu:
            return ["--quipu", self.quipu]
        raise StoreUnproven(
            "seeds backend: no store configured (set SHANTY_SD_STORE or "
            "SHANTY_SD_QUIPU). Refusing: sd would fall back to a default local "
            "store and report an empty board.")

    def prove_store(self) -> StoreProof:
        """`sd where --json` for the configured store, or raise StoreUnproven.

        Run once per tracker and before any other command, so every read this
        tracker returns, empty or not, sits behind it. The proof is CACHED on the
        tracker object: right for one st invocation, but a long-lived process
        holding one tracker never re-proves.

        `sd where` reports the same for a store path that does not exist as for a
        real one (measured, sd 0.0.4), and sd then creates the store on the first
        write. So a local store must EXIST, and the prefix must match: creating a
        board is an explicit admin act, never a side effect of st.
        """
        if self._proof is not None:
            return self._proof
        loc = self._location()
        named = loc[1]
        if not self.prefix:
            raise StoreUnproven(
                f"seeds backend: SHANTY_SD_PREFIX is not set for {named}. It is "
                "required: a missing or wrong store reports the default prefix, and "
                "only the prefix check can tell it from the real board")
        try:
            r = subprocess.run([self._bin, *loc, "where", "--json"], cwd=self.repo,
                               capture_output=True, text=True, timeout=self.timeout,
                               **sdk_subprocess_options())
        except (OSError, subprocess.TimeoutExpired) as e:
            raise StoreUnproven(f"seeds backend: `sd where` for {named} failed: {e}") from e
        if r.returncode != 0:
            raise StoreUnproven(f"seeds backend: `sd where` for {named} exited "
                                f"{r.returncode}: {_failure_reason(r)[:160]}")
        try:
            w = json.loads(r.stdout)
        except ValueError as e:
            raise StoreUnproven(f"seeds backend: `sd where` for {named} returned "
                                f"no JSON: {r.stdout[:120]!r}") from e
        source = w.get("location_source")
        expect_source = loc[0]
        if source != expect_source:
            raise StoreUnproven(
                f"seeds backend: sd resolved its store from {source!r}, not from "
                f"{expect_source} {named}; refusing to read an unproven store")
        if self.store and not os.path.isfile(w.get("database_path") or ""):
            raise StoreUnproven(
                f"seeds backend: no seeds store at {w.get('database_path')!r} "
                f"(SHANTY_SD_STORE={self.store!r}). Refusing: sd would read it as an "
                "empty board and create it on the first write")
        if self.store and w.get("database_path") != os.path.abspath(self.store):
            raise StoreUnproven(
                f"seeds backend: sd reads {w.get('database_path')!r}, configured "
                f"store is {self.store!r}")
        if self.quipu and (w.get("quipu_url") or "").rstrip("/") != self.quipu.rstrip("/"):
            raise StoreUnproven(
                f"seeds backend: sd reads {w.get('quipu_url')!r}, configured "
                f"quipu is {self.quipu!r}")
        if w.get("prefix") != self.prefix:
            raise StoreUnproven(
                f"seeds backend: store {named} has prefix {w.get('prefix')!r}, "
                f"expected {self.prefix!r}")
        self._proof = StoreProof(location_source=source,
                                 database_path=w.get("database_path"),
                                 quipu_url=w.get("quipu_url"), prefix=w.get("prefix"),
                                 graph=w.get("graph"))
        return self._proof

    def deferred_rows(self) -> Answer[list[dict]]:
        """Both deferral representations, selecting dated open rows remotely."""
        rows = {}
        how = "sd list deferred + open --defer-until-present, --limit 0"
        try:
            for status in ("deferred", "open"):
                args = ["list", "--status", status, "--json", "--limit", "0"]
                if status == "open":
                    args.append("--defer-until-present")
                result = self._bd(*args)
                if result.returncode:
                    raise RuntimeError(_failure_reason(result))
                payload = json.loads(result.stdout)
                candidates = payload.get("issues") if isinstance(payload, dict) else None
                if (not isinstance(candidates, list) or payload.get("has_more") is not False
                        or payload.get("total") != len(candidates)):
                    raise ValueError("deferral listing did not prove completeness")
                for row in candidates:
                    if not isinstance(row, dict) or not row.get("id"):
                        raise ValueError("deferral listing returned an invalid issue")
                    if status == "open" and row.get("defer_until") is None:
                        raise ValueError("open deferral listing included an undated issue")
                    rows[row["id"]] = row
            return Answer.complete_read(list(rows.values()), how=how)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            return Answer.capped(list(rows.values()), how=how,
                                 caveat=f"deferral candidates unreadable: {error}")

    def _use_remote_projection(self) -> bool:
        if not self.quipu or not self.prove_store().graph:
            return False
        if self._native_projection is None:
            from .seeds_plate import uses_native_schema
            try:
                self._native_projection = uses_native_schema(self.prove_store(), timeout=self.timeout)
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise StoreUnproven(f"seeds plate format unproven: {error}") from error
        return self._native_projection

    def plate_rows(self, agent: str) -> Answer[list[dict]]:
        """Query both accepted owner spellings before selecting the plate.

        Reading every active issue and filtering its owner locally costs a
        whole-board read on a remote store. Selection still uses br's ranking,
        readiness and partial-read rules; only the candidate set is narrower.
        """
        # Remote plates need candidate fields, not bodies/comments/dependency
        # hydration. Local and older SDK transports retain their CLI contract.
        try:
            projected = self._use_remote_projection()
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            return Answer.capped([], how="Seeds owner plate format proof", caveat=str(error))
        if projected:
            from .seeds_plate import owner_rows
            self._plate_projection_candidates.pop(agent, None)
            answer = owner_rows(self.prove_store(), agent, timeout=self.timeout)
            if answer.complete:
                self._plate_projection_candidates[agent] = answer.exact()
            return answer
        # Most plate polls already hold work. Loading the open queue also
        # hydrates every unread message, then discards it. Probe each held
        # rank in precedence order; uncertainty keeps the full read path.
        from .protocols import _PLATE_RANK
        for status in sorted(_PLATE_RANK, key=_PLATE_RANK.get):
            held = self._owner_rows(agent, status=status)
            if not held.complete:
                break
            if any(not is_message(row.get("title", "")) and not is_unworkable(row)
                   for row in held.exact()):
                return held
        return self._owner_rows(agent)

    def unassigned_open_counts(self) -> tuple[int, int] | None:
        if not self._use_remote_projection():
            return None
        from .seeds_plate import unassigned_counts
        return unassigned_counts(self.prove_store(), timeout=self.timeout)

    @staticmethod
    def _tend_order(rows):
        # Haul queues use the first row: retain SDK priority/creation/id order.
        # Missing dates cannot authorize a different dispatch head.
        from datetime import datetime
        def key(row):
            value = row.get("created_at")
            if not isinstance(value, str):
                raise StoreUnproven("tend row lacks creation ordering evidence")
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo is None:
                raise StoreUnproven("tend creation date lacks timezone")
            return row["priority"], date, row["id"]
        return sorted(rows, key=key)

    def tend_rows(self, owners):
        result = self.feed_rows(owners)
        if result is None:
            return None
        ready, active = result
        return self._tend_order(ready), self._tend_order(active)

    def active_rows(self, owners: list[str]) -> Answer[list[dict]] | None:
        """Fresh active fields for the sweep's roster, including final barriers."""
        if not self._use_remote_projection():
            return None
        from .seeds_plate import owner_rows
        from .inbox import drop_parked
        rows = owner_rows(self.prove_store(), None, feed_owners=tuple(owners),
                          active_only=True, timeout=self.timeout).exact()
        return Answer.complete_read(
            self._tend_order([row for row in drop_parked(rows)
                              if row["status"] == "in_progress"]),
            how="fresh roster-scoped active fields")

    def ready_count(self) -> int | None:
        """Global utilization count from readiness metadata, not issue bodies."""
        if not self._use_remote_projection():
            return None
        from .seeds_plate import ready_count
        return ready_count(self.prove_store(), timeout=self.timeout)

    def feed_rows(self, owners: list[str]) -> tuple[list[dict], list[dict]] | None:
        """Complete Rule Zero fields scoped to idle workers and unassigned work.

        A failed native projection raises; it cannot authorize a hydration
        fallback or an empty plate. Legacy transports keep their SDK path.
        """
        if not self._use_remote_projection():
            return None
        from .seeds_plate import owner_rows, unblocked_ids
        from .inbox import drop_parked
        rows = drop_parked(owner_rows(self.prove_store(), None,
                                    feed_owners=tuple(owners),
                                    timeout=self.timeout).exact())
        ready = [row for row in rows if row["status"] == "open"]
        active = [row for row in rows if row["status"] == "in_progress"]
        ids = unblocked_ids(self.prove_store(), ready, timeout=self.timeout)
        return [row for row in ready if row["id"] in ids], active

    def priority_rows(self, *, ready_candidates=None) -> tuple[list[dict], list[dict]] | None:
        """Lean fields for fleet priority advice; never change mutation reads."""
        if not self._use_remote_projection():
            return None
        from .seeds_plate import owner_rows, unblocked_ids
        rows = owner_rows(self.prove_store(), None, timeout=self.timeout).exact()
        from .inbox import drop_parked
        rows = drop_parked(rows)
        ready = [row for row in rows if row["status"] == "open"]
        active = [row for row in rows if row["status"] == "in_progress"]
        # The advice consumer may prove most open items irrelevant before the
        # dependency read. Active rows preserve the SDK list semantics.
        candidates = ready_candidates(ready, active) if ready_candidates else ready
        unblocked = unblocked_ids(self.prove_store(), candidates, timeout=self.timeout)
        return [row for row in candidates if row["id"] in unblocked], active

    def _owner_rows(self, agent: str, *, include_closed: bool = False,
                    messages_only: bool = False, status: str | None = None) -> Answer[list[dict]]:
        rows, failures = {}, []
        for owner in dict.fromkeys((agent, agent.split("/")[-1])):
            for prefix in (MESSAGE_PREFIXES if messages_only else (None,)):
                try:
                    arguments = ["list", "--assignee", owner, "--json", "--limit", "0"]
                    if status is not None:
                        arguments += ["--status", status]
                    if include_closed:
                        arguments.append("--all")
                    if prefix is not None:
                        arguments += ["--title-contains", prefix]
                    result = self._bd(*arguments)
                    if result.returncode:
                        raise RuntimeError(_failure_reason(result))
                    payload = json.loads(result.stdout)
                    candidates = payload.get("issues") if isinstance(payload, dict) else None
                    if not isinstance(candidates, list):
                        raise ValueError("listing returned no issue array")
                    if payload.get("has_more") is not False or payload.get("total") != len(candidates):
                        raise ValueError("owner listing did not prove completeness")
                    for row in candidates:
                        if not isinstance(row, dict) or not row.get("id"):
                            raise ValueError("listing returned an invalid issue")
                        rows[row["id"]] = row
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                    failures.append(f"sd plate listing failed for owner {owner}: {error}")
        how = f"sd list --assignee for {agent!r} and its short spelling, --limit 0"
        if failures:
            return Answer.capped(list(rows.values()), how=how, caveat="; ".join(failures))
        return Answer.complete_read(list(rows.values()), how=how)

    def inbox_items(self, agent: str, include_closed: bool = False) -> Answer[list[WorkItem]]:
        """Read only this recipient's messages, with closed receipt support."""
        answer = self._owner_rows(agent, include_closed=include_closed, messages_only=True)
        # Each bounded read is ordered, but their union must keep the SDK's
        # global priority/creation/id order before dates leave the projection.
        rows = sorted(answer.at_least(), key=lambda row: (
            row.get("priority", 2), row.get("created_at", ""), row["id"]))
        items = [WorkItem(id=row["id"], title=row.get("title", ""),
                          status=row.get("status", "open"), assignee=row.get("assignee"),
                          priority=row.get("priority", 2)) for row in rows
                 if is_message(row.get("title", ""))]
        how = answer.how + ", --title-contains each of " + "/".join(MESSAGE_PREFIXES) + (", --all" if include_closed else "")
        if answer.complete:
            return Answer.complete_read(items, how=how)
        return Answer.capped(items, how=how, caveat=answer.caveat)

    def plate_ready_ids(self, agent: str) -> Answer[set[str]]:
        """Read readiness only for the owner spellings used by plate selection."""
        try:
            projected = self._use_remote_projection()
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            return Answer.capped(set(), how="Seeds owner readiness format proof", caveat=str(error))
        if projected:
            from .seeds_plate import owner_rows, unblocked_ids
            from .answer import PartialAnswer
            from .inbox import drop_parked
            try:
                rows = self._plate_projection_candidates.get(agent)
                if rows is None:
                    rows = owner_rows(self.prove_store(), agent, timeout=self.timeout).exact()
                candidates = [row for row in drop_parked(rows)
                              if row["status"] == "open" and not is_message(row["title"])]
                ready = unblocked_ids(self.prove_store(), candidates, timeout=self.timeout)
                return Answer.complete_read(ready, how="Seeds scoped readiness of projected owner IDs")
            except (OSError, ValueError, RuntimeError, PartialAnswer) as error:
                return Answer.capped(set(), how="Seeds scoped readiness", caveat=str(error))
        ready = set()
        how = f"sd ready --assignee for {agent!r} and its short spelling, --limit 0"
        try:
            for owner in dict.fromkeys((agent, agent.split("/")[-1])):
                result = self._bd("ready", "--assignee", owner, "--json", "--limit", "0")
                if result.returncode:
                    raise RuntimeError(_failure_reason(result))
                payload = json.loads(result.stdout)
                candidates = payload.get("issues") if isinstance(payload, dict) else payload
                if not isinstance(candidates, list):
                    raise ValueError("readiness returned no issue array")
                if isinstance(payload, dict) and (
                        payload.get("has_more") is not False
                        or payload.get("total") != len(candidates)):
                    raise ValueError("owner readiness did not prove completeness")
                for row in candidates:
                    if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                            or not row["id"].strip()):
                        raise ValueError("owner readiness returned an invalid issue ID")
                    ready.add(row["id"])
            return Answer.complete_read(ready, how=how)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            return Answer.capped(ready, how=how, caveat=f"owner readiness unreadable: {error}")

    @staticmethod
    def _translate(args: "tuple[str, ...]") -> "tuple[str, ...]":
        # br: `comments <id> [--json]`; sd: `comments list <id> [--json]`.
        if len(args) >= 2 and args[0] == "comments" and args[1] not in (
                "add", "list", "delete", "edit", "--help", "-h"):
            return ("comments", "list", *args[1:])
        return args

    def _bd_in(self, repo: "str | None", *args: str) -> subprocess.CompletedProcess:
        self.prove_store()
        actor = os.environ.get("SHANTY_AGENT", "").strip()
        explicit_actor = any(arg == "--actor" or arg.startswith("--actor=") for arg in args)
        identity = ["--actor", actor] if actor and not explicit_actor else []
        cmd = [self._bin, *self._location(), *identity, *self._translate(args)]
        return subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                              timeout=self.timeout, **sdk_subprocess_options())

    def _get_failure(self, item_id, result) -> str:
        where = self.store or self.quipu
        return (f"sd show {item_id} failed: {_failure_reason(result)} — "
                f"seeds store {where}")


def br_like_tracker(get, backend: "str | None" = None, *, repo: "str | None" = None,
                    timeout: "int | None" = None) -> BrTracker:
    """The tracker for a br-like backend, from a deployment-default getter.

    `get(key)` returns a SHANTY_* deployment value or None. `backend` overrides
    SHANTY_BACKEND (an explicit --backend). Every site that builds a br-like
    tracker goes through here, so `seeds` cannot reach one site and miss another.
    """
    from .beads import EXTRA_REPOS_KEY, parse_extra_repos
    backend = backend or get("SHANTY_BACKEND") or "files"
    repo = repo or get("SHANTY_BR_REPO") or get("SHANTY_BEADS_REPO")
    kw = {"timeout": timeout} if timeout is not None else {}
    if backend == "seeds":
        return SdTracker(repo=repo, store=get("SHANTY_SD_STORE"),
                         quipu=get("SHANTY_SD_QUIPU"), prefix=get("SHANTY_SD_PREFIX"),
                         **kw)
    return BrTracker(repo=repo, extra_repos=parse_extra_repos(get(EXTRA_REPOS_KEY)), **kw)
