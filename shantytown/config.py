"""config — shantytown's own TOML: WHO comes up, and when the admin may sleep.

    <root>/shantytown.toml    (optional; absent means the built-in defaults)

THE FILENAME IS `shantytown.toml`, NOT `shanty.toml`, for the same reason the
binary is `st` and not `shanty` (cli.py's docstring): `shanty` is Stiwi's tmux
command — a DIFFERENT program on the same operator's PATH and in the same
workspaces. `shanty.toml` in a repo root is a file that program has every right
to claim, and a config file two tools each believe they own is a config file that
gets edited for the wrong reader. Full name, no ambiguity.

WHY TOML. Deployment plumbing is env-shaped, but the rest is not:

  [env]             WHERE this deployment's plumbing lives — a tracker path, a
                    guard script, a server URL. Flat string values, every one of
                    which is also settable as an environment variable.
  other tables      WHAT the operator wants running, and how much of it. A mode
                    is a NAMED SET of crew plus a policy — nested, list-valued,
                    and edited by a human deciding how many tokens tonight costs.
                    That does not flatten into KEY=value without inventing a
                    syntax (SHANTY_MODE_LITE_CREW="administrator,lead"), and a
                    config syntax nobody can read is a config nobody audits.

tomllib is stdlib on 3.11+, which this package already requires — so the TOML
costs no dependency, and `dependencies = []` in pyproject stays true.

ONE READER, same discipline deployment.py is built on: every surface that needs a
mode, a roster or the hibernate policy calls in here. The comment in deployment.py
about three copies of a six-line resolver is the whole reason this module is not
just `tomllib.load` at each call site.

TWO LOADERS, because the two callers have opposite failure needs, and rounding
them to one answer is a bug in whichever direction you round:

  load()            RAISES ConfigError on malformed TOML or an unknown key. For
                    `st fleet start` — an operator ran a command that launches agents,
                    and silently starting the WRONG SET because a comma was
                    misplaced is worse than not starting. Refuse and say where.
  load_or_default() Never raises. For the STOP-HOOK path, which runs inside a
                    blocking hook in every agent's process: a config typo must
                    not wedge the fleet. It returns the defaults and hands back
                    the error string so the caller can be LOUD about running on
                    defaults — silence there is how a hibernate policy nobody
                    noticed was ignored becomes "the admin never sleeps".

The defaults are deliberately the CHEAP ones: mode `lite` (the administrator
alone) and hibernate `off`. A missing config file must never bring up nineteen
agents, and it must never put an agent to sleep that the operator did not ask to
sleep — the surprising direction of each knob is the one that costs money or
loses work, so the default is the other one.
"""
from __future__ import annotations

from .admin_wake_budget import Policy as AdminWakeBudget, parse as parse_admin_wake_budget

import math
import tomllib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
import os

from .answer import Answer

from . import governor as governor_mod
from . import hostmem as hostmem_mod
from . import quiet_detectors
from . import session_budget as session_budget_mod
from .governor import Policy as GovernorPolicy, GovernorError
from .hostmem import Limits as HostMemLimits
from .session_budget import Limits as SessionLimits
from .protocols import Agent
from .dream import Policy as DreamPolicy
from .cycle_advice import Policy as CycleAdvicePolicy

CONFIG_NAME = "shantytown.toml"

# A mode selects crew by ROLE or by NAME; `*` is every card. Roles are the tier's
# own words (tier.VALID_ROLES) so a mode never invents a vocabulary.
ALL = "*"
ROLE_SELECTORS = ("administrator", "lead", "worker")

# The built-in modes. `lite` is the token-conservation floor: the administrator
# and nobody else, because the admin is the one agent that can decide who else is
# needed. `heavy` is every card that is not retired.
BUILTIN_MODES: dict[str, list[str]] = {
    "lite": ["administrator"],
    "heavy": [ALL],
}
DEFAULT_MODE = "lite"

# hibernate — ONE boolean and one safety valve. It was four trigger values and a
# percentage; docs/stop-policy-spec.md 8.2 argues the collapse. Short version:
# once Rule Zero is rank 2 of one ordered decision, an idle THRESHOLD can never
# change an outcome — crew idle with work ready is already a block, and crew idle
# with nothing dispatchable is not a reason to wake.


class ConfigError(ValueError):
    """The config file exists and is wrong. Always names the file and the key —
    a config error that does not say WHERE is a config error you edit by guessing.
    """


class ConfigSourceError(ConfigError):
    """A selected graph bootstrap is invalid; never guess another tracker."""

    def __init__(self, message, local):
        super().__init__(message)
        self.local = local


@dataclass(frozen=True)
class Hibernate:
    """When may the administrator's stop hook decline to wake it up?

    THE THING BEING GATED, stated precisely, because "hibernate" invites a wrong
    picture: nothing is suspended and no process sleeps. The administrator's Stop
    hook currently DRAINS — it blocks at the end of every turn and re-injects
    whatever arrived, which is what keeps a coordinator awake (and billing) all
    night. Hibernating means that block is SKIPPED while the fleet has nothing
    for the coordinator to decide, so the admin's turn actually ends. It is woken
    the way it is already woken today: `st fleet tend`'s pushes, an `st inbox`, a
    dispatch. Hibernate removes a self-wake; it never removes a wake.

    WHY THE UNDELIVERED EVENTS ARE SAFE. Declining to drain does NOT consume
    anything: stop_event's deferral discipline already distinguishes "not
    delivered" from "delivered" and only marks the latter. A skipped drain leaves
    every event exactly where it was, so the next wake sees the full backlog. If
    that were not already true, this feature would be a work-loss bug.
    """
    enabled: bool = False
    # NOT a schedule to wake ON — a BOUND on how long a pending batch may sit
    # unread while nothing pushes. 0 disables it, which is legitimate: `st fleet tend`
    # pushes, and a push is a wake with a REASON, which beats a timer.
    #
    # There was an `idle_percent` here, and it is gone (spec 8.2): once Rule Zero
    # is rank 2 of one ordered decision, an idle THRESHOLD cannot change an
    # outcome. Crew idle with work ready is already a block; crew idle with
    # nothing dispatchable is not a reason to wake. No third state exists.
    max_quiet_minutes: int = 60


@dataclass(frozen=True)
class Ephemeral:
    """[ephemeral] — bounds on `st agent spawn --ephemeral` (aegis-c01c.2).

    Every number here is a SUPERVISION bound, not a tuning knob: Gas Town's
    polecats were retired partly because a spawned worker could outlive its
    job, spend without limit and fan out unseen. Defaults are deliberately
    small; `max_agents = 0` turns spawning off. docs/ephemeral-agents.md.
    """
    max_agents: int = 2
    lifetime_minutes: int = 60
    max_turns: int = 40
    max_context_k: int = 300
    merge_spacing_minutes: int = 10
    # None = inherit the administrator card's `dangerous` posture.
    unattended: bool | None = None
    require_verified_identity: bool = False
    unattended_uid_ready: bool = False
    # Independent activation gate for the signed controller launch bridge.
    recruitment_launch_ready: bool = False
    review_enqueue_enabled: bool = False
    review_enqueue_command: tuple = ()
    review_enqueue_attended_uid: int | None = None
    review_enqueue_attended_dir: str = ""
    harness_by_job: dict = field(default_factory=dict)
    # aegis-jsp0: the model a job runs, {harness: model}. Spawn copies it onto
    # the job card, so the launch passes --model AND exports SHANTY_MODEL from
    # that one value (X-Quipu-Model). Keyed by harness so a claude slug never
    # reaches a codex job. No entry = no model: the harness default runs and
    # nothing is declared, so provenance stays visibly partial.
    model_by_harness: dict = field(default_factory=dict)
    # aegis-fye: per-harness slot caps, {harness: n}. A harness with no entry is
    # capped by max_agents alone, so an unset table routes exactly as before; 0
    # turns that harness off. The host-wide max_agents still bounds the total.
    max_agents_by_harness: dict = field(default_factory=dict)
    # aegis-fye: queue drain shares per work track, {track: weight}. Empty = OFF
    # (priority-then-age). The quarter plan's split is ops 20, short-term 15,
    # roadmap 50, backlog 15 (ephemeral.SUGGESTED_TRACK_SHARES), opt-in only.
    track_shares: dict = field(default_factory=dict)
    jobs: dict = field(default_factory=dict)
    # aegis-za4f D5: per-job-type bounds, {job: {"lifetime_minutes": n,
    # "max_turns": n}}. A job type with no entry keeps the global bounds above,
    # so a review keeps its short timebox while a task job can get enough turns
    # to read, edit, test and open a PR. aegis-za4f.3 adds "max_concurrent":
    # live jobs of that type at once; over it a spawn queues like any over-cap.
    limits: dict = field(default_factory=dict)
    # aegis-za4f.3: a ticket queued longer than this is reported to the
    # administrator and on its item, once, by the tend reap sweep. It stays
    # queued: the TTL makes a stuck queue visible, it never discards work. 0 = off.
    queue_ttl_minutes: int = 240
    # aegis-xa6w: free-space floor, in GB, on the filesystem worktrees land on
    # (shantytown/disk.py). Below it a spawn queues and the drain holds; tend
    # drains once space returns. 0 = off. disk_path overrides the watched path
    # (default: the worktree storage root, else the st root).
    disk_floor_gb: int = 0
    disk_path: str = ""
    # aegis-c01c.7: signed review verdicts in Quipu (shantytown/gate_verdict.py).
    # Empty = off: no record is written and the merge gate reads none.
    verdict_graph: str = ""         # registered committed graph IRI for the records
    verdict_signer: str = ""        # verifier key id; default st-review.<host>
    verdict_key: str = ""           # signer key file; default $XDG_STATE_HOME/shantytown/verdict-signer.pk8
    # chaski-github-work prefix for `lane release` when a merge job ends unmerged;
    # empty = leave it to chaski's lease.
    lane_release: tuple = ()


@dataclass(frozen=True)
class Fleet:
    """Fleet-wide state that Rule Zero must respect (GitHub #29, #23).

    stood_down — THE QUIET STATE Rule Zero did not have. The gate could only ever
    demand MORE dispatch: there was no state in which standing the fleet down was
    the right answer, so a deliberate quiet period was indistinguishable from
    neglect and the gate could not be satisfied by RESTRAINT. Measured: an operator
    out of usage credits stopped nine of eleven crew on instruction, and the hook
    then blocked every stop demanding they be re-dispatched.

    It is CONFIG, not a runtime flag, for the same reason retirement lives on a
    card: a deliberate shutdown must survive the session that decided it.

    max_load — the capacity ceiling. Rule Zero compared nothing against the host:
    it forced dispatch to 9 agents on an 8-core box at load 33. 0 disables the
    check; the default is expressed per-core, so it travels between hosts.
    """
    stood_down: bool = False
    max_load_per_core: float = 4.0
    # admin_self_slots — how many P0 items the ADMINISTRATOR may have in flight
    # itself (in_progress on its own plate, typically run as in-process
    # subagents) before its own ready P0s stop counting as startable. Feeds the
    # stop policy's P0-plate rank (aegis-c01c.1). 0 = the administrator never
    # starts work itself; only crew and ephemeral slots count as capacity.
    admin_self_slots: int = 1


@dataclass(frozen=True)
class HostPeer:
    """One reachable peer host: the ssh target and the .shanty root there."""
    name: str
    ssh: str
    root: str


@dataclass(frozen=True)
class Config:
    """The whole file, resolved. `path` is None when no file was found — callers
    render that differently from a file that said the same thing by hand, because
    "you are on the defaults" and "your config chose this" need different fixes.
    """
    # Cycle preflight fetch budget; local Git probes keep their shorter bound.
    keep_current_fetch_timeout_seconds: float = 180
    overdue_spec_changes: bool = False
    overdue_external_unlocks: bool = False
    overdue_enabled: bool = False
    # Explicit per-host scheduler cutover; omission preserves local TOML jobs.
    jobs_scheduler: str = "local"
    # The Quipu graph holding this deployment's job declarations. File job
    # config is deprecated (directive crew/scheduled-jobs), so `st work jobs`
    # reads here by default once it is set, with no TOML fallback.
    jobs_graph: str = ""
    # "refuse" (default) or "migrate": a host with live cron/every job files
    # keeps them firing through the migration window instead of losing them
    # silently on deploy. Directive crew/scheduled-jobs: no new timed files.
    jobs_timed_files: str = "refuse"
    # Activation belongs to the producer's declared config, never ambient env.
    escalation_poller_carrier_enabled: bool = False
    mode: str = DEFAULT_MODE
    modes: dict[str, list[str]] = field(default_factory=lambda: dict(BUILTIN_MODES))
    hibernate: Hibernate = field(default_factory=Hibernate)
    admin_wake_budget: AdminWakeBudget = field(default_factory=AdminWakeBudget)
    fleet: Fleet = field(default_factory=Fleet)
    # [crew.<name>] — identity declared IN THIS FILE (GitHub #11). Empty means the
    # file declares no crew, which is the normal case: cards or the graph own it.
    crew: dict[str, Agent] = field(default_factory=dict)
    accounts: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    # [env] — this deployment's plumbing, folded in from env.json (aegis-8calr).
    # KEYS ARE NOT VALIDATED, deliberately, and it is the one table here that
    # isn't: the set is open by construction (a deployment's own guard path, a
    # server URL, a backend name), and refusing an unrecognised one would make
    # this table useless for the thing it exists to hold. Values are strings
    # because every one of them is also settable as an environment variable —
    # that is what a launcher can carry into a pane.
    env: dict[str, str] = field(default_factory=dict)
    # [tmux] socket — folded in from settings/tmux-socket (aegis-8calr).
    tmux_socket: str | None = None
    # [host] — WHICH RIG HOST this deployment is, and how to reach its peers
    # (aegis-5du1bz). `name` is the deployment's own host name as the graph and
    # the cards spell it (vati, macbookair-stiwi); DECLARED, never hostname(1),
    # for the same reason as the tmux socket: an inferred identity changes
    # meaning with the machine you happen to run on, and this one decides which
    # cards `roles sync` is allowed to write. None = single-host deployment,
    # which is every deployment written before this existed.
    host_name: str | None = None
    host_admission_owner: str | None = None
    # [host] peer_census_max_age (seconds): a peer's remembered census older
    # than this is advisory only and never holds local launches (aegis-lfeg).
    host_peer_census_max_age: int = 6 * 60 * 60
    host_min_sync_version: int = 1
    # [host.peers.<name>] ssh = "user@addr", root = "/path/to/.shanty" — how the
    # ephemeral inbox reaches an agent whose card says it lives elsewhere.
    host_peers: dict[str, "HostPeer"] = field(default_factory=dict)
    # [roles.<name>] + [precedence.<axis>] — the deployment's own role vocabulary,
    # as traits (GitHub #37). Empty means "the built-in three", which is what every
    # deployment had before there was anywhere to say otherwise.
    roles: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    precedence: dict[tuple[str, str], int] = field(default_factory=dict)
    # [governor] + [[governor.tier]] — spin the crew down by Claude usage
    # (aegis-hdqej). The DEFAULT IS OFF and it is off by having no tiers, not by a
    # boolean: declaring a tier is the enabling act. Same rule as every other
    # default in this file — the surprising direction is the one that costs
    # something, so a deployment that has never heard of the governor is
    # untouched, and one that writes four tiers does not have to discover a fifth
    # line was required to make them do anything.
    governor: GovernorPolicy = field(default_factory=GovernorPolicy)
    # [session_budget] — the ceiling on ONE session's own run (aegis-xxae9). A
    # different axis from [governor] above, which reads fleet-wide Claude usage:
    # eleven cheap agents and one agent doing eleven deploys look identical on a
    # usage gauge, and it was the second that went unbounded for six hours. Same
    # default-off-by-omission rule as the governor.
    session_budget: SessionLimits = field(default_factory=SessionLimits)
    quiet_time: quiet_detectors.Policy = field(default_factory=quiet_detectors.Policy)
    # [hostmem] — the PHYSICAL brake (aegis-do672). A third axis beside the usage
    # governor and the per-session ceiling: tokens are refilled by waiting, RAM is
    # refilled by something finishing, and a governor that can only see the first
    # will admit an agent onto a box that cannot hold it.
    hostmem: HostMemLimits = field(default_factory=HostMemLimits)
    # [dream] — bounded background reflection on measured spare provider budget.
    # Default OFF: silence must never start spending tokens.
    dream: DreamPolicy = field(default_factory=DreamPolicy)
    # [cycle_advice] — keep-or-cycle tunables. Inert with no signal posted: the
    # table only prices a signal something outside st chose to send.
    cycle_advice: CycleAdvicePolicy = field(default_factory=CycleAdvicePolicy)
    ephemeral: Ephemeral = field(default_factory=Ephemeral)
    # [inbox] store: where NEW durable messages go. "seed" keeps
    # today's inbox seeds; "message-graph" sends through `sd msg` into the
    # per-week message windows, and readers union the legacy seeds with them.
    # Rollback is setting it back to "seed"; window messages stay readable.
    inbox_store: str = "seed"
    # [inbox] operators: the human operator names (aegis-vpy). A crew or job
    # process can never SIGN as one of these: `[from <operator>]` carries an
    # authority no agent has, so the name is attributable only through the
    # operator's own channel or a protected-UID identity bound to it.
    inbox_operators: tuple[str, ...] = ()
    # [harness] — WHICH AGENT PROGRAM, for cards that do not say (harness.py).
    # Two levels, and a card still beats both:
    #
    #     harness.default          the fleet's program
    #     harness.by_role.<role>   that role's program
    #
    # MOST SPECIFIC WINS — card, then role, then fleet, then "claude" — the same
    # rule the trait model uses, because it is the same question ("who decided
    # this, and how narrowly?"). Empty means every card answers for itself, which
    # is every deployment that predates this table.
    harness_default: str | None = None
    harness_by_role: dict[str, str] = field(default_factory=dict)
    harness_required_by_role: dict[str, str] = field(default_factory=dict)
    # [model] — WHICH MODEL, for cards that do not say. Same two levels and the
    # same precedence as [harness], because it is the same question one axis
    # over: harness picks the PROGRAM, model picks what that program runs.
    #
    #     model.default            the fleet's model
    #     model.by_role.<role>     that role's model
    #
    # NOT validated against a known-names list, unlike harness: model slugs are
    # the PROVIDER's vocabulary and they rotate without a shantytown release, so
    # a build-time allowlist here would refuse tomorrow's model and be wrong in
    # the direction that blocks work. The ROLE half is still validated — that is
    # the silently-dropped key, and it fails the other way (applies to nobody,
    # reads as applied).
    model_default: str | None = None
    model_by_role: dict[str, str] = field(default_factory=dict)
    # WHERE AN AGENT GOES WHEN ITS MODEL IS OUT OF BUDGET (Stiwi 2026-09-21:
    # "we hit fable limits. we need to support this in st"). A usage limit is
    # not an outage and not an expired login: the account is fine, the agent is
    # fine, and ONE model is unavailable for a while. Nothing in st could say
    # that, so a limited agent read `idle`, sat on the free list, and every
    # dispatch into it failed with a banner st could not see — the aegis-arma
    # shape exactly, one axis over.
    model_fallback: str | None = None
    model_fallback_by_role: dict[str, str] = field(default_factory=dict)
    path: Path | None = None
    source_origins: dict[str, str] = field(default_factory=dict)
    source_document: dict | None = None
    source_warning: str | None = None

    def catalog(self):
        """The role catalog this file declares, over the built-in three."""
        from .traits import Catalog
        return Catalog(self.roles, self.precedence)

    def selectors(self, mode: str | None = None) -> list[str]:
        """The crew selectors for `mode` (default: the configured mode).

        Raises ConfigError naming the modes that DO exist — an unknown mode is
        the one config mistake an operator makes at the command line, where the
        fix is a list of valid words and nothing else.
        """
        name = mode or self.mode
        if name not in self.modes:
            known = ", ".join(sorted(self.modes)) or "(none)"
            where = f" in {self.path}" if self.path else " (no config file)"
            raise ConfigError(f"unknown mode {name!r}{where}; defined modes: {known}")
        return list(self.modes[name])


def config_path(root) -> Path:
    return Path(root) / CONFIG_NAME


def load(root, *, refresh_source=False) -> Config:
    """Read <root>/shantytown.toml. Absent -> the built-in defaults. Malformed or
    unrecognised or unreadable -> ConfigError.

    UNKNOWN KEYS ARE REFUSED, not ignored. A silently-dropped key is the config
    failure mode this repo has already paid for elsewhere (a hook file that was
    written, deployed, and never read): the operator edits a file, sees no error,
    and believes a policy is in force. `hibernate_percent` instead of
    `idle_percent` must be a refusal at the top of `st fleet start`, not a coordinator
    that mysteriously never sleeps.
    """
    path = config_path(root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        # Preserve the historical no-file behavior for deployments that did not
        # opt into graph configuration; in particular, do not newly read env.json.
        if not os.environ.get("SHANTY_CONFIG_ENTITY"):
            return Config()
        raw = b""
    except OSError as exc:
        # An unreadable declaration is UNKNOWN, never an absent declaration.
        # Defaulting here can reactivate local jobs after a Chaski cutover;
        # execution boundaries rely on this strict read even when supervision
        # uses load_or_default to keep its other sweeps alive.
        raise ConfigError(f"{path}: could not read config ({exc})") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(f"{path}: not valid TOML — {e}") from e
    from . import config_source
    try:
        projection = config_source.project(
            Path(root) if root is not None else path.parent, data,
            lambda value: _resolve(value, path), refresh=refresh_source)
    except config_source.SourceError as exc:
        raise ConfigSourceError(str(exc), _resolve(data, path)) from None
    result = _resolve(projection.data, path)
    return replace(result, source_origins=projection.origins,
                   source_document=projection.document,
                   source_warning=projection.warning,
                   path=None if not raw and projection.document is None else path)


def load_or_default(root) -> tuple[Config, str | None]:
    """(config, error). Never raises — the stop-hook path. The error string is
    returned rather than swallowed so the caller can say out loud that it is
    running on defaults; see the module docstring."""
    try:
        return load(root), None
    except ConfigSourceError as e:
        return replace(e.local, source_warning=str(e)), str(e)
    except ConfigError as e:
        return Config(), str(e)
    except Exception as e:                    # noqa: BLE001 — a hook must not die here
        return Config(), f"{config_path(root)}: could not read config ({e!r})"


# --- parsing ----------------------------------------------------------------

_TOP_KEYS = {"startup", "modes", "hibernate", "admin_wake_budget", "fleet", "crew", "env", "tmux", "dream", "jobs",
             "roles", "precedence", "governor", "session_budget", "hostmem", "quiet_time",
             "harness",
             "model", "host", "keep_current", "cycle_advice", "accounts", "overdue", "memory",
             "ephemeral", "inbox", "escalation_poller"}
_HARNESS_KEYS = {"default", "by_role", "required_by_role"}
_MODEL_KEYS = {"default", "by_role", "fallback", "fallback_by_role"}
_STARTUP_KEYS = {"mode"}
_HIB_KEYS = {"enabled", "max_quiet_minutes"}
_TMUX_KEYS = {"socket"}
_HOST_KEYS = {"name", "peers", "min_sync_version", "admission_owner",
              "peer_census_max_age"}
_HOST_PEER_KEYS = {"ssh", "root"}
_DREAM_KEYS = {"enabled", "interval_minutes", "min_headroom_pct", "domains"}
_CYCLE_ADVICE_KEYS = set(CycleAdvicePolicy.__dataclass_fields__)


def _refuse_unknown(path: Path, where: str, got, allowed: set[str]) -> None:
    unknown = sorted(set(got) - allowed)
    if unknown:
        raise ConfigError(
            f"{path}: unknown key(s) in [{where}]: {', '.join(unknown)}; "
            f"expected one of: {', '.join(sorted(allowed))}")


def _table(path: Path, data: dict, key: str) -> dict:
    val = data.get(key, {})
    if not isinstance(val, dict):
        raise ConfigError(f"{path}: [{key}] must be a table, got {type(val).__name__}")
    return val


def _resolve(data: dict, path: Path) -> Config:
    if not isinstance(data, dict):            # tomllib cannot produce this; be explicit
        raise ConfigError(f"{path}: top level must be a table")
    _refuse_unknown(path, "top level", data, _TOP_KEYS)

    startup = _table(path, data, "startup")
    _refuse_unknown(path, "startup", startup, _STARTUP_KEYS)

    # Operator modes are MERGED OVER the built-ins, never a replacement: a config
    # that defines only `[modes.night]` still has lite and heavy, so `st fleet start
    # --mode lite` cannot stop working because somebody added a third mode. A
    # config MAY redefine lite/heavy — that is a deliberate override of a default,
    # which is what a config file is for.
    modes = dict(BUILTIN_MODES)
    for name, spec in _table(path, data, "modes").items():
        modes[name] = _crew_list(path, name, spec)

    mode = startup.get("mode", DEFAULT_MODE)
    if not isinstance(mode, str):
        raise ConfigError(f"{path}: startup.mode must be a string, got {type(mode).__name__}")
    if mode not in modes:
        known = ", ".join(sorted(modes))
        raise ConfigError(f"{path}: startup.mode = {mode!r} is not a defined mode; "
                          f"defined: {known}")

    # Parsed BEFORE the crew table, because `[crew.<name>] role` is validated
    # against what `[roles.*]` declares (GitHub #37). No ordering hazard: both
    # tables come out of the same already-parsed `data`.
    declared_roles = _roles(path, _table(path, data, "roles"))
    harness_default, harness_by_role, harness_required_by_role = _harness(
        path, _table(path, data, "harness"), declared=set(declared_roles))
    (model_default, model_by_role,
     model_fallback, model_fallback_by_role) = _model(
        path, _table(path, data, "model"), declared=set(declared_roles))
    keep_current = _table(path, data, "keep_current")
    _refuse_unknown(path, "keep_current", keep_current, {"fetch_timeout_seconds"})
    fetch_timeout = keep_current.get("fetch_timeout_seconds", 180)
    if (isinstance(fetch_timeout, bool) or not isinstance(fetch_timeout, (int, float))
            or not math.isfinite(fetch_timeout) or fetch_timeout <= 0):
        raise ConfigError(f"{path}: keep_current.fetch_timeout_seconds must be a finite positive number")
    overdue = _table(path, data, "overdue")
    _refuse_unknown(path, "overdue", overdue, {"enabled", "external_unlocks", "spec_changes"})
    overdue_enabled = overdue.get("enabled", False)
    if type(overdue_enabled) is not bool:
        raise ConfigError(f"{path}: overdue.enabled must be boolean")
    external_unlocks = overdue.get("external_unlocks",False)
    if type(external_unlocks) is not bool:
        raise ConfigError(f"{path}: overdue.external_unlocks must be boolean")
    spec_changes = overdue.get("spec_changes",False)
    if type(spec_changes) is not bool:
        raise ConfigError(f"{path}: overdue.spec_changes must be boolean")
    return Config(mode=mode, modes=modes, overdue_spec_changes=spec_changes, overdue_enabled=overdue_enabled,
                  jobs_scheduler=_jobs_scheduler(path, _table(path, data, "jobs")),
                  jobs_graph=_jobs_graph(path, _table(path, data, "jobs")),
                  jobs_timed_files=_jobs_timed_files(path, _table(path, data, "jobs")),
                  escalation_poller_carrier_enabled=_escalation_poller(
                      path, _table(path, data, "escalation_poller")),
                  overdue_external_unlocks=external_unlocks,
                  accounts=_accounts(path, _table(path, data, "accounts")),
                  memory=_memory(path, _table(path, data, "memory")),
                  keep_current_fetch_timeout_seconds=fetch_timeout,
                  harness_default=harness_default,
                  harness_by_role=harness_by_role,
                  harness_required_by_role=harness_required_by_role,
                  model_default=model_default,
                  model_by_role=model_by_role,
                  model_fallback=model_fallback,
                  model_fallback_by_role=model_fallback_by_role,
                  hibernate=_hibernate(path, _table(path, data, "hibernate")),
                  admin_wake_budget=_admin_wake_budget(path, _table(path, data, "admin_wake_budget")),
                  fleet=_fleet(path, _table(path, data, "fleet")),
                  crew=_crew(path, _table(path, data, "crew"),
                             declared=set(declared_roles)),
                  env=_env(path, _table(path, data, "env")),
                  tmux_socket=_tmux_socket(path, _table(path, data, "tmux")),
                  host_name=_host_name(path, _table(path, data, "host")),
                  host_admission_owner=_host_admission_owner(path, _table(path, data, "host")),
                  host_peer_census_max_age=_host_census_max_age(path, _table(path, data, "host")),
                  host_min_sync_version=_host_sync_version(path, _table(path, data, "host")),
                  host_peers=_host_peers(path, _table(path, data, "host")),
                  roles=declared_roles,
                  precedence=_precedence(path, _table(path, data, "precedence")),
                  governor=_governor(path, _table(path, data, "governor")),
                  quiet_time=_quiet_time(path, _table(path, data, "quiet_time")),
                  session_budget=_session_budget(
                      path, _table(path, data, "session_budget")),
                  hostmem=_hostmem(path, _table(path, data, "hostmem")),
                  dream=_dream(path, _table(path, data, "dream")),
                  cycle_advice=_cycle_advice(path, _table(path, data, "cycle_advice")),
                  ephemeral=_ephemeral(path, _table(path, data, "ephemeral")),
                  inbox_store=_inbox_store(path, _table(path, data, "inbox")),
                  inbox_operators=_inbox_operators(path, _table(path, data, "inbox")),
                  path=path)


INBOX_STORES = ("seed", "message-graph")


def _escalation_poller(path: Path, tbl: dict) -> bool:
    _refuse_unknown(path, "escalation_poller", tbl, {"carrier_enabled"})
    enabled = tbl.get("carrier_enabled", False)
    if type(enabled) is not bool:
        raise ConfigError(f"{path}: escalation_poller.carrier_enabled must be boolean")
    return enabled


def _inbox_store(path: Path, tbl: dict) -> str:
    _refuse_unknown(path, "inbox", tbl, {"store", "operators"})
    store = tbl.get("store", "seed")
    if store not in INBOX_STORES:
        raise ConfigError(f"{path}: inbox.store must be one of {', '.join(INBOX_STORES)}, "
                          f"not {store!r}")
    return store


def _inbox_operators(path: Path, tbl: dict) -> tuple[str, ...]:
    names = tbl.get("operators", [])
    if (not isinstance(names, list)
            or not all(isinstance(n, str) and n.strip() for n in names)):
        raise ConfigError(f"{path}: inbox.operators must be a list of names")
    return tuple(n.strip() for n in names)


def _jobs_scheduler(path: Path, tbl: dict) -> str:
    _refuse_unknown(path, "jobs", tbl, {"scheduler", "graph", "timed_files"})
    scheduler = tbl.get("scheduler", "local")
    if not isinstance(scheduler, str) or scheduler not in {"local", "chaski"}:
        raise ConfigError(f"{path}: jobs.scheduler must be 'local' or 'chaski'")
    return scheduler


def _jobs_graph(path: Path, tbl: dict) -> str:
    graph = tbl.get("graph", "")
    if not isinstance(graph, str) or (graph and not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|^`\\]+", graph)):
        raise ConfigError(f"{path}: jobs.graph must be an absolute IRI (e.g. urn:example:jobs)")
    return graph


def _jobs_timed_files(path: Path, tbl: dict) -> str:
    mode = tbl.get("timed_files", "refuse")
    if mode not in ("refuse", "migrate"):
        raise ConfigError(f"{path}: jobs.timed_files must be 'refuse' or 'migrate'")
    return mode


def _dream(path: Path, tbl: dict) -> DreamPolicy:
    _refuse_unknown(path, "dream", tbl, _DREAM_KEYS)
    enabled = tbl.get("enabled", False)
    interval = tbl.get("interval_minutes", DreamPolicy.interval_minutes)
    headroom = tbl.get("min_headroom_pct", DreamPolicy.min_headroom_pct)
    domains = tbl.get("domains", list(DreamPolicy.domains))
    if not isinstance(enabled, bool):
        raise ConfigError(f"{path}: dream.enabled must be a boolean")
    for key, value in (("interval_minutes", interval),
                       ("min_headroom_pct", headroom)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigError(f"{path}: dream.{key} must be a positive integer")
    if headroom > 100:
        raise ConfigError(f"{path}: dream.min_headroom_pct must be 1-100")
    if (not isinstance(domains, list) or not domains
            or any(not isinstance(x, str) or not x.strip() for x in domains)):
        raise ConfigError(f"{path}: dream.domains must be a non-empty string array")
    return DreamPolicy(enabled=enabled, interval_minutes=interval,
                       min_headroom_pct=headroom,
                       domains=tuple(x.strip() for x in domains))


def _cycle_advice(path: Path, tbl: dict) -> CycleAdvicePolicy:
    _refuse_unknown(path, "cycle_advice", tbl, _CYCLE_ADVICE_KEYS)
    out = {}
    for key, default in vars(CycleAdvicePolicy()).items():
        value = tbl.get(key, default)
        if key == 'model_cache_ttl_seconds':
            if (not isinstance(value, dict) or any(
                    not isinstance(pattern, str) or not pattern.strip()
                    or type(seconds) is not int or seconds <= 0
                    for pattern, seconds in value.items())):
                raise ConfigError(f"{path}: cycle_advice.{key} needs model-pattern = positive integer seconds")
            out[key] = dict(value)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ConfigError(f"{path}: cycle_advice.{key} must be a non-negative number")
        if isinstance(default, int) and not isinstance(value, int):
            raise ConfigError(f"{path}: cycle_advice.{key} must be an integer")
        if key in ("keep_at", "cycle_below") and value > 1:
            raise ConfigError(f"{path}: cycle_advice.{key} must be 0-1")
        out[key] = value
    return CycleAdvicePolicy(**out)


def _harness(path: Path, tbl: dict,
             declared: set[str] | None = None
             ) -> tuple[str | None, dict[str, str], dict[str, str]]:
    """[harness] — which agent PROGRAM, for cards that do not say.

        [harness]
        default = "codex"

        [harness.by_role]
        lead = "claude"
        administrator = "claude"

    WHY NOT `[roles.<name>] harness = …`, which is where a reader looks first:
    that table is the deployment's TRAIT VOCABULARY, its axis names are validated
    against the ontology, and a seventh key there is a typo rather than an
    extension (_roles). Launch config is not a trait — it does not compose, does
    not stack, and has nothing to rank — so mixing it in would mean either
    loosening that validation for everything or special-casing one key. A
    separate table costs one heading and keeps both meanings intact.

    BOTH HALVES ARE VALIDATED, and each catches a different silent failure:

      the harness NAME, against what this build implements. A typo in
      `default` moves EVERY card in the fleet onto a program that does not
      exist, and without this the first symptom is `st agent new` refusing agent by
      agent with UnknownHarness — a fleet-wide config error reported as a
      per-agent launch failure.

      the ROLE NAME, against the built-in three plus whatever [roles.*]
      declares. `[harness.by_role] leed = "codex"` would otherwise be accepted,
      apply to nobody, and read as done — the silently-dropped key this whole
      file refuses to have.
    """
    from . import harness as harness_mod
    from .tier import VALID_ROLES
    _refuse_unknown(path, "harness", tbl, _HARNESS_KEYS)
    known = sorted(h.name for h in harness_mod.all_harnesses())

    def _named(where: str, value) -> str:
        if not isinstance(value, str):
            raise ConfigError(f"{path}: [{where}] must be a harness name (a string), "
                              f"got {type(value).__name__}")
        if value not in known:
            raise ConfigError(
                f"{path}: [{where}] = {value!r} is not a harness this build "
                f"implements; known: {', '.join(known)}. Refusing to default the "
                f"fleet onto a program that cannot be launched.")
        return value

    default = tbl.get("default")
    default = _named("harness] default", default) if default is not None else None

    allowed = set(VALID_ROLES) | set(declared or ())

    def _role_map(key: str) -> dict[str, str]:
        raw = tbl.get(key, {})
        if not isinstance(raw, dict):
            raise ConfigError(f"{path}: [harness.{key}] must be a table, got "
                              f"{type(raw).__name__}")
        out: dict[str, str] = {}
        for role, value in raw.items():
            if role not in allowed:
                raise ConfigError(
                    f"{path}: [harness.{key}] {role!r} is not a role this deployment "
                    f"has; roles: {', '.join(sorted(allowed))}. Declare it as "
                    f"[roles.{role}] to use it here — a rule for a role nobody has "
                    f"applies to nobody and reads as applied.")
            out[role] = _named(f"harness.{key}] {role}", value)
        return out

    return default, _role_map("by_role"), _role_map("required_by_role")


def _memory(path: Path, table: dict) -> dict:
    from .memory_lifecycle import parse
    try:
        return parse(table)
    except ValueError as exc:
        raise ConfigError(f'{path}: {exc}') from None


def _accounts(path: Path, table: dict) -> dict:
    from . import accounts
    try:
        return accounts.parse(table)
    except (accounts.AccountError, GovernorError) as exc:
        raise ConfigError(f'{path}: {exc}') from None


def _model(path: Path, tbl: dict, declared: set[str] | None = None) -> tuple:
    """[model] — which MODEL, for cards that do not say.

        [model]
        default = "gpt-5.6-terra"

        [model.by_role]
        administrator = "gpt-5.6-terra"
        worker = "gpt-5.6-luna"

    Deliberately the same shape, the same precedence and the same table position
    as [harness], because it is the same question one axis over — harness picks
    the PROGRAM, model picks what that program runs. A reader who has learned one
    has learned the other, and `[roles.<name>] model = …` is refused here for the
    reason spelled out in _harness: that table is the trait vocabulary.

    ONE HALF IS VALIDATED, AND THE ASYMMETRY IS THE POINT:

      the ROLE name, exactly as _harness does. `[model.by_role] wrker = "…"` must
      not be accepted, apply to nobody and read as applied.

      the MODEL name is NOT checked against a list, and must not be. Slugs are
      the PROVIDER's vocabulary — `gpt-5.6-terra` and `claude-opus-5` are minted
      and retired on their schedule, not on shantytown's. A build-time allowlist
      would refuse a model released after the installed version and be wrong in
      the direction that BLOCKS WORK, which is the worse direction for a knob
      whose failure is otherwise loud: a bad slug is rejected by the harness
      itself, at launch, naming the model. Compare harness, where the name space
      IS this build's (all_harnesses()) and an unknown one is unlaunchable — so
      validating there is checkable and refusing here would be guessing.
    """
    from .tier import VALID_ROLES
    _refuse_unknown(path, "model", tbl, _MODEL_KEYS)

    def _slug(where: str, value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{path}: [{where}] must be a model name (a "
                              f"non-empty string), got {value!r}")
        return value

    default = tbl.get("default")
    default = _slug("model] default", default) if default is not None else None

    raw = tbl.get("by_role", {})
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [model.by_role] must be a table, got "
                          f"{type(raw).__name__}")
    allowed = set(VALID_ROLES) | set(declared or ())
    by_role: dict[str, str] = {}
    for role, value in raw.items():
        if role not in allowed:
            raise ConfigError(
                f"{path}: [model.by_role] {role!r} is not a role this deployment "
                f"has; roles: {', '.join(sorted(allowed))}. Declare it as "
                f"[roles.{role}] to use it here — a rule for a role nobody has "
                f"applies to nobody and reads as applied.")
        by_role[role] = _slug(f"model.by_role] {role}", value)

    # THE FALLBACK HALF. Same shape, same precedence, same validation asymmetry —
    # the role name is checked against this deployment's roles, the model slug is
    # not checked against anything, for the reason spelled out above.
    #
    # It is a SEPARATE key rather than a list under `default` because the two
    # answer different questions and are read at different moments: `default` is
    # what a card runs, `fallback` is where it goes when that model says no. A
    # list would make "which one am I on right now" a matter of position, and the
    # thing reading it is a supervisor acting unattended on a limited agent.
    fallback = tbl.get("fallback")
    fallback = _slug("model] fallback", fallback) if fallback is not None else None
    raw_fb = tbl.get("fallback_by_role", {})
    if not isinstance(raw_fb, dict):
        raise ConfigError(f"{path}: [model.fallback_by_role] must be a table, "
                          f"got {type(raw_fb).__name__}")
    fallback_by_role: dict[str, str] = {}
    for role, value in raw_fb.items():
        if role not in allowed:
            raise ConfigError(
                f"{path}: [model.fallback_by_role] {role!r} is not a role this "
                f"deployment has; roles: {', '.join(sorted(allowed))}. Declare "
                f"it as [roles.{role}] to use it here — a rule for a role "
                f"nobody has applies to nobody and reads as applied.")
        fallback_by_role[role] = _slug(f"model.fallback_by_role] {role}", value)
    return default, by_role, fallback, fallback_by_role


def _session_budget(path: Path, tbl: dict) -> SessionLimits:
    """[session_budget] — the per-session ceiling (aegis-xxae9).

    Same split as _governor for the same reason: session_budget.py owns what a
    valid limit IS, this function owns putting the file name on the complaint.
    """
    try:
        return session_budget_mod.parse(tbl)
    except session_budget_mod.BudgetError as e:
        raise ConfigError(f"{path}: {e}") from e


def _hostmem(path: Path, tbl: dict) -> HostMemLimits:
    """[hostmem] — the physical admission floor (aegis-do672).

    Same split as _governor and _session_budget: hostmem.py owns what a valid floor
    IS, this function owns putting the file name on the complaint.
    """
    try:
        return hostmem_mod.parse(tbl)
    except hostmem_mod.HostMemError as e:
        raise ConfigError(f"{path}: {e}") from e


def _governor(path: Path, tbl: dict) -> GovernorPolicy:
    """[governor] — the usage tiers (aegis-hdqej).

    The VALIDATION lives in governor.py, next to the thing it describes; this
    function's whole job is to put the FILE NAME on the error. That split is
    deliberate: `ConfigError` promises to name where to edit, and a
    `GovernorError` escaping raw would tell an operator their tier is wrong
    without telling them which of several possible files it is in.
    """
    try:
        return governor_mod.parse(tbl)
    except governor_mod.GovernorError as e:
        raise ConfigError(f"{path}: {e}") from e


def _roles(path: Path, tbl: dict) -> dict[str, dict[str, list[str]]]:
    """[roles.<name>] — a role as its TRAIT VALUES (GitHub #37).

        [roles.advisor]
        attachment = "unattached"
        workIntake = ["consulted"]

    AXIS NAMES ARE VALIDATED, unlike [env]'s keys: this table's vocabulary is the
    ontology's six axes and a seventh is a typo, not an extension. A dropped
    `attachement` would leave an advisor silently inside the reporting tree — the
    exact failure the trait model exists to remove — so it refuses and names the
    axes. VALUES are not validated against a fixed list, because the value sets are
    the deployment's to extend; an unknown value simply never matches a rule.
    """
    from .traits import AXES, canonical_axis
    out: dict[str, dict[str, list[str]]] = {}
    for role, axes in tbl.items():
        if not isinstance(axes, dict):
            raise ConfigError(f"{path}: [roles.{role}] must be a table of axes, got "
                              f"{type(axes).__name__}")
        got: dict[str, list[str]] = {}
        for axis, val in axes.items():
            canon = canonical_axis(axis)
            if canon not in AXES:
                raise ConfigError(
                    f"{path}: [roles.{role}] unknown trait axis {axis!r}; the axes "
                    f"are: {', '.join(sorted(AXES))}")
            if isinstance(val, str):
                got[canon] = [val]
            elif isinstance(val, list) and all(isinstance(v, str) for v in val):
                got[canon] = list(val)
            else:
                raise ConfigError(
                    f"{path}: [roles.{role}] {axis} must be a string or a list of "
                    f"strings, got {type(val).__name__}")
        out[role] = got
    return out


def _precedence(path: Path, tbl: dict) -> dict[tuple[str, str], int]:
    """[precedence.<axis>] — which value wins when stacked roles conflict.

        [precedence.scope]
        fleet-wide = 3
        domain-scoped = 2
        single-task = 1

    Per AXIS VALUE, not per role: a role that is specific on one axis and generic on
    another gets misranked by a single per-role number, and this is the form that
    matches what "most-specific wins" actually means. Declaring it at all is
    OPTIONAL — with no ranks, a conflicting stack refuses (traits.AmbiguousTrait)
    rather than st picking a winner, which is the whole point.
    """
    from .traits import AXES
    out: dict[tuple[str, str], int] = {}
    for axis, values in tbl.items():
        if axis not in AXES:
            raise ConfigError(f"{path}: [precedence.{axis}] is not a trait axis; "
                              f"the axes are: {', '.join(sorted(AXES))}")
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: [precedence.{axis}] must be a table of "
                              f"value = rank, got {type(values).__name__}")
        for value, rank in values.items():
            if isinstance(rank, bool) or not isinstance(rank, int):
                raise ConfigError(
                    f"{path}: [precedence.{axis}] {value} must be an integer rank "
                    f"(higher wins), got {type(rank).__name__}")
            out[(axis, value)] = rank
    return out


def _env(path: Path, tbl: dict) -> dict[str, str]:
    """[env] — the plumbing values env.json used to hold (aegis-8calr).

    NO KEY VALIDATION (see Config.env): the set is open. What IS validated is the
    SHAPE of each value, because the one mistake this table invites is writing a
    table or a list where a string belongs —

        [env]
        QUIPU_SERVER = { host = "graph.example", port = 8000 }   # refused

    — and the consumer of that value is `os.environ`-shaped, so it would either
    stringify into nonsense or blow up far from the file that caused it. Booleans
    and numbers ARE accepted and stringified: `true` and `1` are what an operator
    will write, and refusing them would be pedantry about a value that has exactly
    one honest rendering.
    """
    out: dict[str, str] = {}
    for k, v in tbl.items():
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (str, int, float)):
            out[k] = str(v)
        else:
            raise ConfigError(
                f"{path}: [env] {k} must be a string (or a number/bool), got "
                f"{type(v).__name__}. Every value here is also settable as an "
                f"environment variable, so it has to be one string.")
    return out


def _host_sync_version(path: Path, tbl: dict) -> int:
    value = tbl.get("min_sync_version", 1)
    if type(value) is not int or value < 1:
        raise ConfigError(f"{path}: [host] min_sync_version must be a positive integer")
    return value


def _host_name(path: Path, tbl: dict) -> str | None:
    """[host] name — this deployment's own rig host (aegis-5du1bz).

    DECLARED, like the tmux socket, and for the same reason. The value is an
    identity the graph and the cards are keyed on, so it must not depend on which
    machine or container happens to evaluate it. An empty string reads as unset.
    """
    _refuse_unknown(path, "host", tbl, _HOST_KEYS)
    v = tbl.get("name")
    if v is None:
        return None
    if not isinstance(v, str):
        raise ConfigError(f"{path}: [host] name must be a string, got "
                          f"{type(v).__name__}")
    return v.strip() or None


def _host_admission_owner(path: Path, tbl: dict) -> str | None:
    value = tbl.get("admission_owner")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}: [host] admission_owner must be a non-empty string")
    owner = value.strip()
    if owner not in {_host_name(path, tbl), *_host_peers(path, tbl)}:
        raise ConfigError(f"{path}: [host] admission_owner must name this host or a declared peer")
    return owner


def _host_census_max_age(path: Path, tbl: dict) -> int:
    value = tbl.get("peer_census_max_age", 6 * 60 * 60)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{path}: [host] peer_census_max_age must be a positive "
                          "integer number of seconds")
    return value


def _host_peers(path: Path, tbl: dict) -> dict:
    """[host.peers.<name>] — how to reach each OTHER host's st (aegis-5du1bz).

        [host.peers.macbookair-stiwi]
        ssh  = "stiwi@mac.example"
        root = "/opt/st/.shanty"

    Both keys are required: the relay is `ssh <ssh> st --root <root> inbox …`,
    and a peer missing either half is a peer that cannot be reached, which is
    worse than one that is not declared because it looks configured.
    """
    peers = tbl.get("peers")
    if peers is None:
        return {}
    if not isinstance(peers, dict):
        raise ConfigError(f"{path}: [host.peers] must be a table of tables")
    out = {}
    for name, spec in peers.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: [host.peers.{name}] must be a table")
        _refuse_unknown(path, f"host.peers.{name}", spec, _HOST_PEER_KEYS)
        ssh, root = spec.get("ssh"), spec.get("root")
        for k, v in (("ssh", ssh), ("root", root)):
            if not isinstance(v, str) or not v.strip():
                raise ConfigError(f"{path}: [host.peers.{name}] {k} must be a "
                                  f"non-empty string")
        out[name] = HostPeer(name=name, ssh=ssh.strip(), root=root.strip())
    return out


def _tmux_socket(path: Path, tbl: dict) -> str | None:
    """[tmux] socket — folded in from `settings/tmux-socket` (aegis-8calr).

    Still DECLARED rather than inferred from the ambient $TMUX, which is the whole
    argument in tmux.py: an env var is what an operator's shell happens to hold,
    and a fleet whose identity changes depending on which pane you ran a command
    from is the bug that made every agent report DOWN. Folding the one-line file
    into the config changes WHERE it is declared, not that it is.
    """
    _refuse_unknown(path, "tmux", tbl, _TMUX_KEYS)
    v = tbl.get("socket")
    if v is None:
        return None
    if not isinstance(v, str):
        raise ConfigError(f"{path}: [tmux] socket must be a string, got "
                          f"{type(v).__name__}")
    return v.strip() or None


def _crew_list(path: Path, mode: str, spec) -> list[str]:
    """`[modes.<name>] crew = [...]` -> the selector list.

    Selectors are VALIDATED here as shapes (`*`, a role, or a bare name), not
    against the live registry: a mode may legitimately name an agent whose card
    does not exist yet (a config is written before a crew is hired). Whether a
    named agent EXISTS is resolve_crew's question, and it answers it against the
    roster it was handed rather than guessing here.
    """
    if not isinstance(spec, dict):
        raise ConfigError(f"{path}: [modes.{mode}] must be a table with a `crew` "
                          f"list, got {type(spec).__name__}")
    _refuse_unknown(path, f"modes.{mode}", spec, {"crew"})
    crew = spec.get("crew")
    if crew is None:
        raise ConfigError(f"{path}: [modes.{mode}] has no `crew` list — a mode that "
                          f"selects nobody would start nothing and report success")
    if isinstance(crew, str) or not isinstance(crew, list):
        raise ConfigError(f"{path}: [modes.{mode}] crew must be a LIST of strings "
                          f"(e.g. crew = [\"administrator\", \"lead\"]), got "
                          f"{type(crew).__name__}")
    out: list[str] = []
    for item in crew:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{path}: [modes.{mode}] crew entries must be non-empty "
                              f"strings; got {item!r}")
        out.append(item.strip())
    if not out:
        raise ConfigError(f"{path}: [modes.{mode}] crew is EMPTY — a mode that selects "
                          f"nobody would start nothing and report success")
    return out


# The card fields a human may DECLARE. `pane` is included but optional — omitted,
# it is generated (tier.pane_for), which is the whole point of that change.
_CREW_KEYS = {"role", "reports_to", "pane", "workspace", "workspace_source",
              "model", "harness", "account", "auto_failover", "dangerous", "retired", "chrome", "harness_options"}


def _crew(path: Path, tbl: dict, declared: set[str] | None = None) -> dict:
    """[crew.<name>] -> Agent, a HUMAN-AUTHORED registry (GitHub #11).

    A legitimate source of truth, not a cache: a deployment with no ontology and
    no interest in one declares its crew here and is done. That is why the keys
    are the card's own fields rather than a reduced subset — a source of truth you
    cannot express your whole fleet in is a projection wearing a different hat.

    Validated the same way everything else in this file is: an unknown key is
    REFUSED, because a silently-dropped `workspace` is an agent launched in the
    wrong directory with no error anywhere.

    `declared` is the set of role names `[roles.*]` declares in the SAME FILE
    (GitHub #37). Without it this gate read `role not in VALID_ROLES`, and that
    was the last place the closed enum still decided what may exist: a deployment
    could declare `[roles.advisor]` and then be REFUSED for assigning it to a crew
    member three lines further down, while `st fleet roles set <agent> advisor` — which
    goes through the catalog — succeeded. Two paths to one fact, disagreeing, and
    the file-authored one lost.

    `None` means "nobody passed the roles table" and falls back to the built-in
    three, which is what a caller constructing a crew with no config gets. That is
    a degradation to the previous behaviour, never to a wider one.
    """
    from .tier import VALID_ROLES, pane_for
    allowed = set(VALID_ROLES) | set(declared or ())
    out: dict[str, Agent] = {}
    for name, spec in tbl.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: [crew.{name}] must be a table, got "
                              f"{type(spec).__name__}")
        _refuse_unknown(path, f"crew.{name}", spec, _CREW_KEYS)
        role = spec.get("role", "worker")
        if role not in allowed:
            raise ConfigError(
                f"{path}: [crew.{name}] role = {role!r} is not one of "
                f"{', '.join(sorted(allowed))}. Declare it as [roles.{role}] in "
                f"this file to use it here.")
        for flag in ("dangerous", "retired", "chrome", "auto_failover"):
            if flag in spec and not isinstance(spec[flag], bool):
                raise ConfigError(f"{path}: [crew.{name}] {flag} must be true or "
                                  f"false, got {spec[flag]!r}")
        from .harness_options import validate
        try:
            options = validate(spec.get("harness_options"))
        except ValueError as error:
            raise ConfigError(f"{path}: [crew.{name}] {error}") from error
        out[name] = Agent(
            name=name, role=role, reports_to=spec.get("reports_to"),
            harness_options=options,
            pane=spec.get("pane") or pane_for(name),
            workspace=spec.get("workspace"),
            workspace_source=spec.get("workspace_source"),
            model=spec.get("model"), harness=spec.get("harness"),
            account=spec.get("account"), auto_failover=spec.get("auto_failover"),
            dangerous=bool(spec.get("dangerous", False)),
            chrome=bool(spec.get("chrome", False)),
            # None when the TOML does not mention it (aegis-6hfmi) — a registry
            # entry that is silent about retirement must not clear one that the
            # card records. `retired = false` in the TOML still un-retires.
            retired=None if spec.get("retired") is None
            else bool(spec.get("retired")))
    return out


class TomlRegistry:
    """The Registry protocol over [crew.<name>] in shantytown.toml.

    THE THIRD IMPLEMENTATION, and the first one a human writes by hand. files is a
    projection (generated cards), quipu is a graph (needs a server); this is the
    deployment that wants neither — identity in the same file as the modes, in a
    format an operator can read and diff.

    READ-ONLY on purpose. `set` would mean rewriting a hand-authored, commented
    TOML from a dataclass, which loses every comment and reorders every table —
    so `roles set` against this registry refuses rather than quietly mangling the
    file it was pointed at. Edit the file; it is the source of truth.
    """

    def __init__(self, root):
        self._root = root

    def _crew(self) -> dict:
        return load(self._root).crew

    def get(self, name: str) -> Agent:
        crew = self._crew()
        if name not in crew:
            raise LookupError(
                f"no such agent: {name} (looked in [crew.{name}] of "
                f"{config_path(self._root)})")
        return crew[name]

    def all(self) -> Answer[list[Agent]]:
        crew = self._crew()
        if not crew:
            # EMPTY IS NOT NOBODY. A config with no [crew] table declares no crew
            # at all, which almost certainly means this registry was selected by
            # mistake — and returning [] would render an empty roster at exit 0,
            # the blank-answer failure this repo keeps paying for.
            raise LookupError(
                f"{config_path(self._root)} declares no [crew.<name>] tables, so "
                f"the toml registry has nothing to read. Declare the crew there, "
                f"or use --registry files/quipu.")
        return Answer.complete_read(
            sorted(crew.values(), key=lambda a: a.name),
            how=f"TomlRegistry: every [crew.<name>] in {config_path(self._root)}",
        )

    def empty_note(self) -> str | None:
        """None — and this registry earns it the same way FilesRegistry does, by
        making the ambiguous case impossible: `all()` RAISES when no [crew] table
        is declared, so an empty list can never be returned at all. There is no
        state in which "nobody exists" and "I looked in the wrong place" could
        arrive here as the same value."""
        return None

    def set(self, agent: Agent) -> None:
        raise LookupError(
            f"the toml registry is READ-ONLY: {config_path(self._root)} is "
            f"hand-authored, and rewriting it from a dataclass would drop every "
            f"comment and reorder every table. Edit it directly — it is the "
            f"source of truth.")


_FLEET_KEYS = {"stood_down", "max_load_per_core", "admin_self_slots"}


_EPHEMERAL_KEYS = {"max_agents", "lifetime_minutes", "max_turns", "max_context_k",
                   "merge_spacing_minutes", "unattended", "require_verified_identity", "unattended_uid_ready", "recruitment_launch_ready", "harness_by_job", "model_by_harness",
                   "verdict_graph", "verdict_signer", "verdict_key", "lane_release", "jobs", "limits",
                   "job_servers", "review_enqueue_enabled", "review_enqueue_command",
                   "review_enqueue_attended_uid", "review_enqueue_attended_dir",
                   "max_agents_by_harness", "track_shares", "queue_ttl_minutes",
                   "disk_floor_gb", "disk_path"}
EPHEMERAL_JOBS = ("review", "merge", "triage", "task")


def _ephemeral(path: Path, tbl: dict) -> Ephemeral:
    _refuse_unknown(path, "ephemeral", tbl, _EPHEMERAL_KEYS)
    values = {}
    for key in ("max_agents", "lifetime_minutes", "max_turns", "max_context_k",
                "merge_spacing_minutes", "queue_ttl_minutes", "disk_floor_gb"):
        value = tbl.get(key, getattr(Ephemeral, key))
        # max_agents and spacing may be 0 (off / no gap), and a zero queue TTL
        # means no TTL; a zero lifetime or budget would end every job at its
        # first stop, which is a typo.
        floor = 0 if key in ("max_agents", "merge_spacing_minutes", "queue_ttl_minutes",
                             "disk_floor_gb") else 1
        if isinstance(value, bool) or not isinstance(value, int) or value < floor:
            raise ConfigError(f"{path}: ephemeral.{key} must be an integer >= {floor}, "
                              f"got {value!r}")
        values[key] = value
    disk_path = tbl.get("disk_path", "")
    if (not isinstance(disk_path, str) or any(c in disk_path for c in "\r\n\0")
            or disk_path and not Path(disk_path).is_absolute()):
        raise ConfigError(f"{path}: ephemeral.disk_path must be an absolute path, "
                          f"got {disk_path!r}")
    values["disk_path"] = disk_path
    unattended = tbl.get("unattended")
    if unattended is not None and not isinstance(unattended, bool):
        raise ConfigError(f"{path}: ephemeral.unattended must be true or false")
    verified = tbl.get("require_verified_identity", False)
    if type(verified) is not bool:
        raise ConfigError(f"{path}: ephemeral.require_verified_identity must be true or false")
    uid_ready = tbl.get("unattended_uid_ready", False)
    if type(uid_ready) is not bool:
        raise ConfigError(f"{path}: ephemeral.unattended_uid_ready must be true or false")
    recruitment_ready = tbl.get("recruitment_launch_ready", False)
    if type(recruitment_ready) is not bool:
        raise ConfigError(f"{path}: ephemeral.recruitment_launch_ready must be true or false")
    enqueue_enabled = tbl.get("review_enqueue_enabled", False)
    enqueue_command = tbl.get("review_enqueue_command", [])
    if type(enqueue_enabled) is not bool:
        raise ConfigError(f"{path}: ephemeral.review_enqueue_enabled must be true or false")
    if (not isinstance(enqueue_command, list) or len(enqueue_command) > 32
            or any(not isinstance(x, str) or not x or len(x) > 4096
                   or any(c in x for c in '\r\n\0') for x in enqueue_command)
            or enqueue_command and not Path(enqueue_command[0]).is_absolute()
            or enqueue_enabled and not enqueue_command):
        raise ConfigError(f"{path}: ephemeral.review_enqueue_command needs an absolute adapter argv")
    values['review_enqueue_enabled'] = enqueue_enabled
    values['review_enqueue_command'] = tuple(enqueue_command)
    attended_uid = tbl.get('review_enqueue_attended_uid')
    attended_dir = tbl.get('review_enqueue_attended_dir', '')
    if (attended_uid is not None and (type(attended_uid) is not int or attended_uid < 0)
            or not isinstance(attended_dir, str) or len(attended_dir) > 4096
            or any(c in attended_dir for c in '\r\n\0')
            or attended_dir and (not Path(attended_dir).is_absolute() or '..' in Path(attended_dir).parts)):
        raise ConfigError(f"{path}: attended enqueue needs an explicit UID and absolute private state path")
    values['review_enqueue_attended_uid'] = attended_uid
    values['review_enqueue_attended_dir'] = attended_dir
    by_job = tbl.get("harness_by_job", {})
    if not isinstance(by_job, dict):
        raise ConfigError(f"{path}: [ephemeral.harness_by_job] must be a table")
    _refuse_unknown(path, "ephemeral.harness_by_job", by_job, set(EPHEMERAL_JOBS))
    for job, harness in by_job.items():
        if not isinstance(harness, str) or not harness.strip():
            raise ConfigError(f"{path}: ephemeral.harness_by_job.{job} must be a harness name")
    by_harness_model = tbl.get("model_by_harness", {})
    if not isinstance(by_harness_model, dict):
        raise ConfigError(f"{path}: [ephemeral.model_by_harness] must be a table")
    for harness, model in by_harness_model.items():
        if (not isinstance(model, str) or not model.strip()
                or any(c in model for c in '\r\n\0')):
            raise ConfigError(f"{path}: ephemeral.model_by_harness.{harness} must be a "
                              f"model name (a non-empty string), got {model!r}")
    values["model_by_harness"] = dict(by_harness_model)
    for key in ("verdict_graph", "verdict_signer", "verdict_key"):
        value = tbl.get(key, "")
        if not isinstance(value, str) or any(c in value for c in '"<>\\\n '):
            raise ConfigError(f"{path}: ephemeral.{key} must be a plain string")
        values[key] = value
    release = tbl.get("lane_release", [])
    if not isinstance(release, list) or not all(isinstance(x, str) and x for x in release):
        raise ConfigError(f"{path}: ephemeral.lane_release must be a list of strings")
    values["lane_release"] = tuple(release)
    limits = tbl.get("limits", {})
    if not isinstance(limits, dict):
        raise ConfigError(f"{path}: [ephemeral.limits] must be a table")
    _refuse_unknown(path, "ephemeral.limits", limits, set(EPHEMERAL_JOBS))
    parsed_limits = {}
    for job, bounds in limits.items():
        if not isinstance(bounds, dict):
            raise ConfigError(f"{path}: [ephemeral.limits.{job}] must be a table")
        _refuse_unknown(path, f"ephemeral.limits.{job}", bounds,
                        {"lifetime_minutes", "max_turns", "max_concurrent"})
        for key, value in bounds.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"{path}: ephemeral.limits.{job}.{key} must be an "
                                  f"integer >= 1, got {value!r}")
        parsed_limits[job] = dict(bounds)
    values["limits"] = parsed_limits
    by_harness = tbl.get("max_agents_by_harness", {})
    if not isinstance(by_harness, dict):
        raise ConfigError(f"{path}: [ephemeral.max_agents_by_harness] must be a table")
    for harness, cap in by_harness.items():
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
            raise ConfigError(f"{path}: ephemeral.max_agents_by_harness.{harness} must be an "
                              f"integer >= 0, got {cap!r}")
    values["max_agents_by_harness"] = dict(by_harness)
    from .ephemeral import TRACKS
    shares = tbl.get("track_shares", {})
    if not isinstance(shares, dict):
        raise ConfigError(f"{path}: [ephemeral.track_shares] must be a table")
    # A misspelt track would silently get no share at all; refuse it.
    _refuse_unknown(path, "ephemeral.track_shares", shares, set(TRACKS))
    for track, share in shares.items():
        if isinstance(share, bool) or not isinstance(share, int) or share < 0:
            raise ConfigError(f"{path}: ephemeral.track_shares.{track} must be an "
                              f"integer >= 0, got {share!r}")
    if shares and sum(shares.values()) <= 0:
        raise ConfigError(f"{path}: ephemeral.track_shares needs at least one share > 0 "
                          "(remove the table to turn shares off)")
    values["track_shares"] = dict(shares)
    from .job_tools import validate_job_servers, validate_specs
    try:
        jobs = validate_specs(tbl.get("jobs", {}), EPHEMERAL_JOBS,
                              validate_job_servers(tbl.get("job_servers", {})))
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    return Ephemeral(unattended=unattended, require_verified_identity=verified,
                     unattended_uid_ready=uid_ready,
                     recruitment_launch_ready=recruitment_ready,
                     harness_by_job=dict(by_job), jobs=jobs, **values)


def _fleet(path: Path, tbl: dict) -> Fleet:
    _refuse_unknown(path, "fleet", tbl, _FLEET_KEYS)
    down = tbl.get("stood_down", Fleet.stood_down)
    if not isinstance(down, bool):
        raise ConfigError(f"{path}: fleet.stood_down must be true or false, "
                          f"got {down!r}")
    load = tbl.get("max_load_per_core", Fleet.max_load_per_core)
    if isinstance(load, bool) or not isinstance(load, (int, float)) or load < 0:
        raise ConfigError(f"{path}: fleet.max_load_per_core must be a "
                          f"non-negative number (0 disables the check), "
                          f"got {load!r}")
    slots = tbl.get("admin_self_slots", Fleet.admin_self_slots)
    if isinstance(slots, bool) or not isinstance(slots, int) or slots < 0:
        raise ConfigError(f"{path}: fleet.admin_self_slots must be a "
                          f"non-negative integer (0 = the administrator never "
                          f"starts work itself), got {slots!r}")
    return Fleet(stood_down=down, max_load_per_core=float(load),
                 admin_self_slots=slots)


def _hibernate(path: Path, tbl: dict) -> Hibernate:
    _refuse_unknown(path, "hibernate", tbl, _HIB_KEYS)
    enabled = tbl.get("enabled", Hibernate.enabled)
    if not isinstance(enabled, bool):
        raise ConfigError(f"{path}: hibernate.enabled must be true or false, "
                          f"got {enabled!r}")
    mins = tbl.get("max_quiet_minutes", Hibernate.max_quiet_minutes)
    if not isinstance(mins, int) or isinstance(mins, bool) or mins < 0:
        raise ConfigError(f"{path}: hibernate.max_quiet_minutes must be a "
                          f"non-negative integer (0 disables the bound), "
                          f"got {mins!r}")
    return Hibernate(enabled=enabled, max_quiet_minutes=mins)


# --- selectors -> a roster --------------------------------------------------

@dataclass(frozen=True)
class Roster:
    """Who a mode resolves to, against a real registry.

    `skipped_retired` and `unknown` are carried rather than dropped because both
    are things the operator needs told: a mode that names a retired agent is not
    starting it (and must say so, or `st fleet start` looks like it silently ignored a
    line of config), and a mode that names an agent with no card is a typo the
    command should refuse on rather than start a smaller fleet than asked for.
    """
    names: list[str] = field(default_factory=list)
    skipped_retired: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


# Start order: the coordinator FIRST, then leads, then workers. Not cosmetic — a
# worker that comes up while its lead is down has its stop events RISE to the
# administrator with `lead-unreachable` (tier.py Q3), so booting bottom-up
# manufactures exactly the escalation the tier exists to avoid. Alphabetical
# within a tier so a boot is reproducible.
#
# THE SAME TREE ORDER tend.py uses, and deliberately NOT the throttle's `survival`
# band — see the long note beside tend.py's copy for why an interim draft merged
# them and why that was reverted. Bring-up is a reporting-tree question; survival
# is a shed-order question.
_TIER_ORDER = {"administrator": 0, "keeper": 1, "lead": 1, "worker": 2}


def resolve_crew(selectors, agents: list[Agent]) -> Roster:
    """Selectors + the roster -> the ordered list of agents to bring up.

    A RETIRED CARD IS NEVER SELECTED, whatever the selector said — including `*`.
    Retirement is a durable, deliberate shutdown (tend.py: a watchdog that could
    not tell "died" from "was killed on purpose" reverted a considered shutdown of
    eight agents in about sixty seconds). `st fleet start --mode heavy` is the exact
    command that would resurrect a retiree, so the exclusion lives here, in the
    resolver both the command and the config path share, and it is REPORTED.
    """
    by_name = {a.name: a for a in agents}
    retired = {a.name for a in agents if bool(getattr(a, "retired", False))}
    picked: list[str] = []
    skipped: list[str] = []
    unknown: list[str] = []

    def take(name: str) -> None:
        if name in retired:
            if name not in skipped:
                skipped.append(name)
            return
        if name not in picked:
            picked.append(name)

    for sel in selectors:
        if sel == ALL:
            for a in agents:
                take(a.name)
        elif sel in ROLE_SELECTORS:
            for a in agents:
                if a.role == sel:
                    take(a.name)
        elif sel in by_name:
            take(sel)
        else:
            unknown.append(sel)

    picked.sort(key=lambda n: (_TIER_ORDER.get(by_name[n].role, 9), n))
    return Roster(names=picked, skipped_retired=skipped, unknown=unknown)


def _quiet_time(path: Path, tbl: dict) -> quiet_detectors.Policy:
    try:
        return quiet_detectors.parse(tbl)
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _admin_wake_budget(path, tbl):
    try:
        return parse_admin_wake_budget(tbl)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
