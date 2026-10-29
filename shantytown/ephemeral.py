"""ephemeral — short-lived, SUPERVISED agents for one job (aegis-c01c.2).

`st agent spawn --ephemeral --job review|merge|triage|task --item ID` starts an
agent that does one job, reports the result to the administrator and is torn
down. docs/ephemeral-agents.md is the design; this module is the mechanism.

WHY EVERY RULE HERE IS A SUPERVISION RULE. Gas Town's ephemeral "polecats" were
retired under CREW-ONLY partly because a spawned worker escaped supervision: it
could outlive its job, spend without bound, merge on its own say-so, or vanish
without anyone hearing. So an ephemeral agent here always has an owner (the
administrator), a deadline, a turn and context budget, a host-wide cap, a
result that is ALWAYS reported (clean, timeout, budget, dead pane or stopped),
and a teardown that tend can never undo by respawning it.

THE LEDGER IS THE TRUTH. `<root>/ephemeral/<name>.json` records the job, its
bounds and its result. The crew card is an ordinary worker card so the census,
the governor, `st crew` and the ONE launcher see the agent with no special path;
the ledger is what says "this card is ephemeral, and here is when it ends".

Everything that touches tmux, git, the tracker or the event store is injected,
so the rules can be tested without any of them.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PREFIX = "eph-"
JOBS = ("review", "merge", "triage", "task")
VERDICTS = ("approve", "request-changes", "merged", "blocked", "done", "failed")
#: Fleet directive 10/21: ALL reviews on codex; important work on Claude.
DEFAULT_HARNESS = {"review": "codex", "merge": "claude", "triage": "claude",
                   "task": "claude"}
MAX_ATTEMPTS = 3
#: Untracked paths provisioning writes into a workspace. They are the launcher's
#: kit, not the agent's output, so they never make a worktree "hold work".
KIT_PATHS = (".mcp.json", ".claude", ".agents", ".codex", "AGENTS.md", "CLAUDE.md",
             ".shantytown-tooling.json")
LAUNCHING, LIVE, ENDING, DONE = "launching", "live", "ending", "done"
#: How long a LAUNCHING job may have no pane before the reaper calls it dead.
#: Covers the whole launch (codex readiness waits included). Without it a tend
#: pass between "ledger written" and "pane up" reaped the job as died, removed
#: the card, and the pane then came up with no ledger, no cap slot and no bounds.
LAUNCH_GRACE_S = 600
#: The stop-event reason a job RESULT carries. It is a finished job, never a
#: stopped crew member to re-dispatch (tier.GOVERNANCE_REASONS renders it apart).
RESULT_REASON = "ephemeral-result"
_NAME = re.compile(r"eph-[a-z]+-[0-9a-f]{6}")
_ITEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class Refused(Exception):
    """A spawn/stop/retry/report the rules do not allow. The message is the reason."""


# --- naming + the ledger ------------------------------------------------------

def is_ephemeral_name(name: str | None) -> bool:
    """Cheap, IO-free test. Hot paths (Rule Zero's free-worker scan) use this."""
    return bool(name) and bool(_NAME.fullmatch(name))


def new_name(job: str, token: Callable[[], str] = lambda: secrets.token_hex(3)) -> str:
    return f"{PREFIX}{job}-{token()}"


def ledger_dir(root) -> Path:
    return Path(root) / "ephemeral"


def _path(root, name: str) -> Path:
    if not is_ephemeral_name(name):
        raise Refused(f"{name!r} is not an ephemeral agent name")
    return ledger_dir(root) / f"{name}.json"


def read(root, name: str) -> dict | None:
    try:
        return json.loads(_path(root, name).read_text())
    except FileNotFoundError:
        return None


def write(root, rec: dict) -> None:
    p = _path(root, rec["name"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2, sort_keys=True))
    os.replace(tmp, p)


def provision_worktree(root, name: str, repo, *, ensure=None) -> str:
    """Record job-owned destinations BEFORE provisioning, including interruptions.

    The ordinary ledger lock serializes this with result recording and teardown.
    Persistent agents use the existing provisioner without creating a ledger.
    """
    from .workspace import ensure_worktree, worktree_for, _shared_repo, WorkspaceError
    ensure = ensure_worktree if ensure is None else ensure
    if not is_ephemeral_name(name):
        return ensure(repo, name)
    with lock(root):
        rec = read(root, name)
        if rec is None or rec.get('state') not in (LAUNCHING, LIVE):
            raise WorkspaceError(f'no active ephemeral job for {name}')
        shared = _shared_repo(repo).resolve()
        dest = worktree_for(shared, name).absolute()
        entry = dict(workspace=str(dest), worktree_of=str(shared))
        entries = rec.setdefault('worktrees', [])
        if entry not in entries:
            entries.append(entry)
            write(root, rec)
        return ensure(shared, name)


def records(root) -> list[dict]:
    out = []
    for p in sorted(ledger_dir(root).glob(f"{PREFIX}*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return out


def live(root) -> list[dict]:
    """Every job not yet torn down. ENDING counts: its pane may still be up."""
    return [r for r in records(root) if r.get("state") in (LAUNCHING, LIVE, ENDING)]


def free_slots(root) -> int:
    """Ephemeral slots free on this host: the cap minus live jobs. The plug
    stop_policy.ephemeral_free_slots reads (aegis-c01c.1, Rule Zero)."""
    from . import config
    cfg, _err = config.load_or_default(root)
    return max(0, cfg.ephemeral.max_agents - len(live(root)))


def is_ephemeral(root, name: str | None) -> bool:
    return is_ephemeral_name(name) and (root is None or read(root, name) is not None)


@contextmanager
def lock(root):
    """One spawn admission at a time on this host: cap check + ledger write are
    one step, or two concurrent spawns both see room for one."""
    d = ledger_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# --- admission ----------------------------------------------------------------

@dataclass(frozen=True)
class Request:
    job: str
    item: str
    harness: str | None = None
    repo: str | None = None          # GitHub owner/name
    pr: int | None = None
    checkout: str | None = None      # local shared checkout for the worktree
    head: str | None = None          # merge: the exact head the item pins (aegis-c01c.7)
    request_id: str | None = None    # merge: chaski's work request id, for lane release


def validate(req: Request) -> None:
    if req.job not in JOBS:
        raise Refused(f"unknown job {req.job!r}; one of {', '.join(JOBS)}")
    if not req.item or not _ITEM.fullmatch(req.item):
        raise Refused("--item must be an opaque work item id")
    # The name half becomes a PATH ($GT_ROOT/<name>), so dot segments are refused.
    if req.repo is not None and (not _REPO.fullmatch(req.repo) or any(
            part in (".", "..") for part in req.repo.split("/"))):
        raise Refused("--repo must be owner/name")
    if req.job in ("review", "merge") and (not req.repo or not req.pr):
        raise Refused(f"a {req.job} job needs --repo owner/name and --pr N")
    if req.pr is not None and req.pr < 1:
        raise Refused("--pr must be a positive number")
    if req.job == "merge" and not _SHA.fullmatch(req.head or ""):
        raise Refused("a merge job merges exactly the item's head: pass --head <40-hex sha> "
                      "or route it through an item carrying chaski's work request")
    if req.request_id is not None and not re.fullmatch(r"[0-9a-f]{64}", req.request_id):
        raise Refused("request_id must be chaski's 64-hex work request id")


def harness_for(req: Request, policy) -> str:
    if req.harness:
        return req.harness
    return (getattr(policy, "harness_by_job", {}) or {}).get(
        req.job, DEFAULT_HARNESS[req.job])


def authority(actor: str | None, role_of: Callable[[str], str | None], *,
              require_verified: bool = False) -> None:
    """Administrators manage jobs; migration mode also admits a human shell.
    With verified identity required, callers resolve the protected principal first."""
    if actor is None:
        if require_verified:
            raise Refused("ephemeral mutations require a verified protected UID identity")
        return
    if is_ephemeral_name(actor):
        raise Refused("an ephemeral agent cannot spawn, stop or retry ephemeral agents")
    if role_of(actor) != "administrator":
        raise Refused(f"{actor} is not the administrator; ephemeral agents are "
                      "managed by the administrator (route the ask there)")


def cap_refusal(root, policy) -> str:
    cap = policy.max_agents
    if cap <= 0:
        return "ephemeral spawning is off ([ephemeral] max_agents = 0)"
    running = live(root)
    if len(running) >= cap:
        names = ", ".join(r["name"] for r in running)
        return (f"over cap: {len(running)}/{cap} ephemeral agent(s) live ({names}); "
                "refused, not queued. Stop one or raise [ephemeral] max_agents")
    return ""


def lane_refusal(root, repo: str, spacing_minutes: int, now: float) -> str:
    """The repo's serialized merge lane: one merge job at a time, and a gap
    between them. A merge job HOLDS the lane for its whole life."""
    merges = [r for r in records(root) if r.get("job") == "merge" and r.get("repo") == repo]
    holder = next((r for r in merges if r.get("state") in (LAUNCHING, LIVE, ENDING)), None)
    if holder:
        return f"merge lane for {repo} is held by {holder['name']}; one merge at a time"
    # Spacing follows MERGES. A job that ended without merging (blocked, failed,
    # stopped) frees the lane at once: there is no deploy to space behind.
    ended = [r.get("ended_at") or 0 for r in merges
             if (r.get("result") or {}).get("verdict") == "merged"]
    last = max(ended, default=0)
    wait = last + spacing_minutes * 60 - now
    if wait > 0:
        return (f"merge lane for {repo} is spacing merges {spacing_minutes}m apart; "
                f"next slot in {int(wait // 60) + 1}m")
    return ""


def plan(req: Request, *, root, policy, actor, administrator, host, now,
         role_of, name=None, attempt=1, retry_of=None) -> dict:
    """Admit or refuse, and build the ledger record. Writes nothing."""
    validate(req)
    authority(actor, role_of, require_verified=policy.require_verified_identity)
    if not administrator:
        raise Refused("no administrator card on this host; nobody would receive "
                      "the result, so nothing is spawned")
    if refusal := cap_refusal(root, policy):
        raise Refused(refusal)
    if req.job == "merge":
        if refusal := lane_refusal(root, req.repo, policy.merge_spacing_minutes, now):
            raise Refused(refusal)
    name = name or new_name(req.job)
    return {
        "name": name, "job": req.job, "item": req.item, "repo": req.repo,
        "pr": req.pr, "checkout": req.checkout, "harness": harness_for(req, policy),
        "head": req.head, "request_id": req.request_id,
        "administrator": administrator, "spawned_by": actor or "operator",
        "host": host, "spawned_at": now,
        "deadline": now + policy.lifetime_minutes * 60,
        "max_turns": policy.max_turns, "max_context_k": policy.max_context_k,
        "turns": 0, "state": LAUNCHING, "attempt": attempt, "retry_of": retry_of,
        "workspace": None, "worktree_of": None, "result": None,
    }


def card_for(rec: dict, *, unattended: bool) -> dict:
    """An ordinary worker card. `first` is the survival band a governor tier
    sheds first: an ephemeral job is the most deferrable work on the host."""
    card = {"role": "worker", "roles": ["worker", "first"],
            "reports_to": rec["administrator"], "pane": f"st-{rec['name']}",
            "harness": rec["harness"], "workspace": rec["workspace"],
            "dangerous": bool(unattended), "retired": False}
    if rec.get("host"):
        card["host"] = rec["host"]
    return card


# --- the job prompt -----------------------------------------------------------

_COMMON = """You are {name}, an EPHEMERAL {job} agent. You do this one job, report, and are torn down.
Work item: {item}{target}. Your working directory is your own worktree; touch nothing outside it.
Bounds: you end at {deadline} UTC or after {max_turns} turns, whichever comes first. You report to {administrator}.
You never spawn agents, never take other board work, and never change items other than {item}.

When you are done, report EXACTLY ONCE (this posts your result on {item}, tells {administrator}, and tears you down):
  st agent spawn --report --verdict <{verdicts}> --summary-file -   (summary on stdin, under 1500 chars)
If you cannot do the job, report --verdict blocked with what is missing. Do not keep trying past your bounds.
"""

_JOBS = {
    "review": """JOB: an INDEPENDENT, NON-AUTHOR review of {repo}#{pr}.
1. Read the PR at its current head: `gh pr view {pr} --repo {repo} --json headRefOid,author,title,body,files`
   and `gh pr diff {pr} --repo {repo}`. Record the head SHA you reviewed.
2. If you (or the agent identity you run as) authored any commit on it, report --verdict blocked: a review must be independent.
3. Review for correctness, tests that can fail, security and scope. Check CI with `gh pr checks {pr} --repo {repo}`.
4. Post ONE verdict comment on the PR naming the exact head SHA, headed APPROVE or REQUEST CHANGES with numbered
   findings: `gh pr comment {pr} --repo {repo} --body-file -`. (One shared GitHub account: a GitHub approval is
   impossible and does not count. The approval that counts is the signed verdict record st writes in step 5.)
5. NEVER push, never merge, never edit the branch. Report with the head you read and the comment's URL:
     st agent spawn --report --verdict <approve|request-changes> --head <sha> --evidence <comment-url> --summary-file -
   st signs that verdict as a Quipu GateApproval record naming you as the reviewer; the merge gate reads it.""",
    "merge": """JOB: merge {repo}#{pr} at EXACTLY head {head} THROUGH THE SERIALIZED MERGE LANE. st holds the lane for {repo}
for you for as long as you live; it is why no other merge can run beside you. Never merge any other PR or head.
1. `gh pr view {pr} --repo {repo} --json headRefOid,mergeable,mergeStateStatus,reviews,author,isDraft`
2. Require ALL of: not draft; every required check green (`gh pr checks {pr} --repo {repo} --required`);
   an approval from an agent OTHER than the author, on the CURRENT head (a signed Quipu verdict record; the
   shared GitHub account means a GitHub APPROVE usually cannot exist); no unresolved request-changes.
   An outside (non-crew) contribution is never merged by an agent: report blocked.
3. Merge ONLY with st's guarded merge command, which re-checks the lane, the head, CI, a non-author approval
   and the author's association in code before it calls gh with the head pinned:
     st agent spawn --merge --head {head}
   If the PR's head is no longer {head}, report blocked: a new head needs a new review.
   NEVER run `gh pr merge` yourself, never `--admin`, never push to the base branch, never bypass or
   edit branch protection, never force-push.
4. If any condition is unproven or the merge is refused, report --verdict blocked with the reason. Otherwise --verdict merged.""",
    "triage": """JOB: triage the failure behind {item}{target_short}.
1. Find the failing run (`gh run list` / `gh pr checks` / the item text) and read its log.
2. Name the cause: flaky, infra, or a real defect (file:line). Reproduce locally if cheap.
3. A fix goes on your own branch and a PR (`st repo pr`), never onto main. Small and obvious only; else describe it.
4. Report --verdict done with the diagnosis (and PR link if any), or blocked.""",
    "task": """JOB: do {item}'s acceptance criteria. Read it with `st work item show {item}`.
Commit on your own branch; open a PR if code changed (`st repo pr`). Never push to main.
Report --verdict done with what changed and the PR link, or blocked.""",
}


def prompt(rec: dict) -> str:
    target = f" — {rec['repo']}#{rec['pr']}" if rec.get("repo") and rec.get("pr") else (
        f" — {rec['repo']}" if rec.get("repo") else "")
    fields = dict(rec, target=target, target_short=target,
                  verdicts="|".join(VERDICTS),
                  deadline=time.strftime("%Y-%m-%dT%H:%M", time.gmtime(rec["deadline"])))
    return (_COMMON.format(**fields) + "\n" + _JOBS[rec["job"]].format(**fields)).strip()


# --- delivering the job: paste, SEE it, submit, SEE the turn start -----------
#
# THE BUG THIS CLOSES (aegis-g9w, live twice on the Mac 10/28). The job went in
# through send(), which types the text and presses Enter in the same burst.
# Claude Code absorbed the long write as `[Pasted text #1 +N lines]`, the Enter
# was eaten by the paste, and the job sat at turn 0 until its deadline while the
# delivery check counted it delivered. One manual Enter to the pane started it.
#
# So delivery is four observed steps, never one fire-and-forget write:
#   1. the composer is EMPTY before anything is typed (else refuse: never type
#      onto, or press Enter on, text the job did not put there);
#   2. type the job with NO Enter, and wait until the box shows it (the paste
#      placeholder, or the job's own last line) and holds nothing else;
#   3. press Enter as its OWN keystroke;
#   4. see the turn start: the agent process is STILL the pane's foreground
#      (not a shell: an agent that crashed on Enter left a shell prompt, and
#      that is "launch failed", never "started"), its box is drawn and empty,
#      AND a positive sign of work shows: a busy marker, a spinner, or the
#      context-left figure dropping. An echo of the job is not work.
#      No start -> press Enter again, but only while the box still holds just
#      the job, a bounded number of times; then "launch failed".

PASTE_TOKEN = re.compile(r"\[Pasted text #\d+(?: \+\d+ lines)?\]")
SUBMIT_ATTEMPTS = 3
LOOK_S = 0.4
SHOW_LOOKS = 20      # ~8s for the box to show the typed job
START_LOOKS = 15     # ~6s per Enter for the turn to start
_PROMPT = "\u276f"   # the Claude Code composer glyph
_BORDER = set("\u2500\u2501")
#: A Claude Code spinner line, e.g. "✶ Roosting…" or "· Finagling… (1s · thinking)".
_SPINNER = re.compile(r"^\s*[^\w\s\u276f\u2500\u23bf]\s+\w[\w-]*\u2026")
_CTX_LEFT = re.compile(r"(\d{1,3})% left")
EMPTY, OURS, PARTIAL, FOREIGN, UNSEEN = "empty", "ours", "partial", "foreign", "unseen"


def _composer(screen: str):
    """(raw prompt line, plain body lines, plain lines above) of the LAST
    composer frame on screen, or None. A frame is a line opening with the
    prompt glyph and closed by a border row below it; transcript echoes of
    earlier messages carry the glyph but no border under them."""
    from .triage import strip_attrs
    raw = screen.splitlines()
    while raw and not strip_attrs(raw[-1]).strip():
        raw.pop()
    plain = [strip_attrs(line) for line in raw]
    for i in range(len(plain) - 1, max(-1, len(plain) - 200), -1):
        if not plain[i].lstrip().startswith(_PROMPT):
            continue
        body = []
        for row in plain[i:]:
            s = row.strip()
            if s and set(s) <= _BORDER:
                return raw[i], body, plain[:i]
            body.append(row)
        return None
    return None


def box_state(screen: str, text: str) -> str:
    """What the composer holds, judged against the job text we typed.

    EMPTY (nothing, or only the dimmed suggestion), OURS (only our text and the
    job's last line is in), PARTIAL (only our text, still arriving), FOREIGN
    (anything we did not type) or UNSEEN (no composer frame on screen)."""
    from .triage import input_state, INPUT_EMPTY, INPUT_PLACEHOLDER
    frame = _composer(screen)
    if frame is None:
        return UNSEEN
    prompt_raw, body, _above = frame
    first = body[0].split(_PROMPT, 1)[1] if body else ""
    pieces = [first.strip("\xa0 \t")] + [row.strip("\xa0 \t") for row in body[1:]]
    if not any(pieces[1:]) and input_state(prompt_raw) in (INPUT_EMPTY, INPUT_PLACEHOLDER):
        return EMPTY
    pasted = False
    for piece in pieces:
        rest, n = PASTE_TOKEN.subn("", piece)
        pasted = pasted or n > 0
        rest = rest.strip("\xa0 \t")
        if rest and rest not in text:
            return FOREIGN
    last = text.rstrip().splitlines()[-1].strip() if text.strip() else ""
    joined = "\n".join(pieces)
    return OURS if pasted or (last and last in joined) else PARTIAL


def _ctx_left(screen: str) -> int | None:
    from .triage import strip_attrs
    found = _CTX_LEFT.findall(strip_attrs(screen))
    return int(found[-1]) if found else None


def turn_started(before: str, screen: str, text: str) -> bool:
    """Does the screen show the job's turn WORKING? The agent's box must be
    drawn and have let go of the job (a vanished box is a dead UI, not a
    submit), AND one positive sign of work must show: a busy marker, a spinner
    above the box, or the context-left figure lower than before typing. The
    caller separately requires the agent process to still be alive."""
    from .triage import mid_flight
    if box_state(screen, text) != EMPTY:
        return False
    if mid_flight(screen):
        return True
    frame = _composer(screen)
    above = frame[2] if frame else screen.splitlines()
    if any(_SPINNER.match(row) for row in above[-6:]):
        return True
    was, now = _ctx_left(before), _ctx_left(screen)
    return was is not None and now is not None and now < was


def deliver(text: str, *, type_text, submit, capture, alive, sleep=time.sleep,
            attempts: int = SUBMIT_ATTEMPTS, show_looks: int = SHOW_LOOKS,
            start_looks: int = START_LOOKS, look_s: float = LOOK_S) -> tuple[bool, str]:
    """Put the job in the box and start its turn, or say exactly why not.

    Returns (started, what happened). Never presses Enter unless the box holds
    only text this call typed; every failure leaves the job for the caller to
    end as "launch failed" rather than idle until its deadline. `alive()` says
    whether the agent process is still the pane's foreground: True, False (a
    shell is back) or None (cannot tell). Started needs a True."""
    before = capture()
    state = box_state(before, text)
    for _ in range(show_looks if state == UNSEEN else 0):
        sleep(look_s)
        before = capture()
        state = box_state(before, text)
        if state != UNSEEN:
            break
    if state == UNSEEN:
        return False, "no composer on screen; nothing typed"
    if state != EMPTY:
        return False, ("the composer already holds text st did not put there; "
                       "refused: nothing typed, Enter withheld")
    type_text(text)
    screen = before
    for _ in range(show_looks):
        sleep(look_s)
        screen = capture()
        state = box_state(screen, text)
        # Only OURS ends the wait. A FOREIGN frame can be transient (seen live
        # once, right after a turn: a redraw mid-type), so it is judged at the
        # end of the wait, and Enter is pressed only on a frame that is OURS.
        if state == OURS:
            break
    if state == FOREIGN:
        return False, "the composer holds text that is not the job's; Enter withheld"
    if state != OURS:
        return False, f"the job never showed in the composer ({state}); Enter withheld"
    for n in range(1, attempts + 1):
        if alive() is False:
            return False, "the agent exited to the shell; Enter withheld"
        submit()
        for _ in range(start_looks):
            sleep(look_s)
            screen = capture()
            live = alive()
            if live is False:
                return False, (f"the agent exited to the shell after Enter {n}; "
                               "not started")
            if live and turn_started(before, screen, text):
                return True, f"turn started after {n} Enter(s)"
        state = box_state(screen, text)
        if state != OURS:
            return False, (f"no turn started and the composer no longer holds just "
                           f"the job ({state}); Enter not pressed again")
    return False, f"no turn started after {attempts} Enters; the job is still in the box"


# --- the guarded merge (only a live merge job, only its own PR) ---------------

#: Associations that make a PR crew/owner work. Anything else is an outside
#: contribution, which an agent never merges (DIRECTIVE 10/21).
INSIDE = ("OWNER", "MEMBER", "COLLABORATOR")
_SHA = re.compile(r"[0-9a-f]{40}")


def merge_gate(rec: dict | None, head: str, pr: dict, reviews: list, checks: list,
               verdict: dict | None = None) -> str:
    """Why this merge must NOT happen, or "". Pure: the caller fetched `pr`
    (GET /repos/R/pulls/N), `reviews` and the head's check runs. Enforced in
    code so "reviews never merge", the pinned head and the lane do not rest on
    prompt text alone."""
    if rec is None or rec.get("job") != "merge":
        return "only a merge job may merge; review, triage and task jobs never do"
    if rec.get("state") not in (LAUNCHING, LIVE):
        return f"{rec['name']} is no longer live; its merge lane is released"
    if not _SHA.fullmatch(head or ""):
        return "--head must be the full 40-hex head SHA you verified"
    if rec.get("head") and head != rec["head"]:
        return (f"this job merges exactly the item's head {rec['head'][:12]}; "
                f"--head {head[:12]} is a different commit")
    if (pr.get("head") or {}).get("sha") != head:
        return "the PR head moved since you verified it; re-verify, never merge a moving head"
    if pr.get("state") != "open" or pr.get("merged"):
        return "the PR is not open"
    if pr.get("draft"):
        return "the PR is a draft"
    if pr.get("author_association") not in INSIDE:
        return "outside contribution: agents never merge these; report blocked for a human"
    author = (pr.get("user") or {}).get("login")
    latest = {}
    for r in reviews:
        login = (r.get("user") or {}).get("login")
        if login and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[login] = r
    if any(r.get("state") == "CHANGES_REQUESTED" for r in latest.values()):
        return "a reviewer's latest review requests changes"
    # aegis-c01c.7: a SIGNED agent verdict (gate_verdict.approval, verified by
    # Quipu) stands in for the GitHub approval the shared account cannot give.
    if verdict and verdict.get("blocking"):
        return "a reviewer agent's signed verdict requests changes on this head"
    github_ok = any(login != author and r.get("state") == "APPROVED" and r.get("commit_id") == head
                    for login, r in latest.items())
    if not github_ok and not (verdict and verdict.get("approved")):
        why = ""
        if verdict and verdict.get("author_agent_unknown") and verdict.get("approvals"):
            why = " (the PR's author agent is unknown, so no verdict can approve it)"
        return ("no non-author APPROVE on the current head: neither a GitHub review nor a "
                "trusted signed verdict from an agent other than the author" + why)
    if not checks:
        return "no check runs on the head; green is unproven"
    bad = [c.get("name", "?") for c in checks
           if c.get("status") != "completed"
           or c.get("conclusion") not in ("success", "neutral", "skipped")]
    if bad:
        return "checks not green on the head: " + ", ".join(sorted(bad)[:5])
    return ""


# --- identity that does not rest on the environment ---------------------------

def inside_ephemeral(root, *, cwd: Path, ancestors: list[int],
                     pane_pid: Callable[[str], int | None]) -> str | None:
    """The live ephemeral job this process runs inside, or None. Independent of
    $SHANTY_AGENT, which a pane can unset: the process is inside a job's
    workspace, or descends from the shell of a job's tmux pane."""
    cwd = Path(cwd).resolve()
    for rec in live(root):
        ws = rec.get("workspace")
        if ws:
            ws = Path(ws).resolve()
            if cwd == ws or ws in cwd.parents:
                return rec["name"]
        try:
            pid = pane_pid(f"st-{rec['name']}")
        except Exception:  # noqa: BLE001
            pid = None
        if pid and pid in ancestors:
            return rec["name"]
    return None


def ancestor_pids(start: int | None = None, run=subprocess.run) -> list[int]:
    """This process's ancestry, via ps (works on Linux and macOS)."""
    out, pid = [], os.getpid() if start is None else start
    for _ in range(64):
        out.append(pid)
        try:
            r = run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                    text=True, timeout=5)
            ppid = int(r.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        if ppid <= 1 or ppid == pid:
            break
        pid = ppid
    return out


# --- per-Stop budget (event-driven: the agent's own Stop hook) ----------------

def on_stop(root, name: str, context_k: float | None, now: float) -> str:
    """Count one turn and return why the job must END now, or "". Called from
    the Stop hook, so enforcement needs no poller: every turn boundary checks."""
    with lock(root):
        rec = read(root, name)
        if rec is None or rec.get("state") not in (LAUNCHING, LIVE):
            return ""
        rec["turns"] = int(rec.get("turns", 0)) + 1
        write(root, rec)
    if now >= rec["deadline"]:
        return "timeout"
    if rec["turns"] >= rec["max_turns"]:
        return "turn budget"
    if context_k is not None and context_k >= rec["max_context_k"]:
        return "context budget"
    return ""


# --- ending: result -> report -> teardown -------------------------------------

def mark_live(root, name: str) -> None:
    with lock(root):
        rec = read(root, name)
        if rec is not None and rec.get("state") == LAUNCHING:
            rec["state"] = LIVE
            write(root, rec)


def record_result(root, name: str, verdict: str, summary: str, cause: str,
                  now: float) -> dict:
    """Write the result ONCE. A second ending (a report racing a timeout) keeps
    the first result, so the administrator never hears two different stories."""
    with lock(root):              # a report racing a reaper: one read-modify-write
        rec = read(root, name)
        if rec is None:
            raise Refused(f"no ledger entry for {name}")
        if rec.get("result") is None:
            rec["result"] = {"verdict": verdict, "summary": summary[:1500],
                             "cause": cause, "at": now}
            rec["state"] = ENDING
            rec["ended_at"] = now
            write(root, rec)
    return rec


def report_text(rec: dict) -> str:
    r = rec["result"]
    target = f" {rec['repo']}#{rec['pr']}" if rec.get("pr") else ""
    head = (f"[ephemeral {rec['job']}{target}] {rec['name']} ({rec['harness']}, "
            f"attempt {rec.get('attempt', 1)}): {r['verdict'].upper()}")
    if r["cause"] != "report":
        head += f" — ended by {r['cause']}"
    return head + ("\n\n" + r["summary"] if r["summary"] else "")


def notify(rec: dict, *, persist_event, comment) -> list[str]:
    """Tell the administrator and the item. Each leg is best-effort and named
    when it fails: one lost leg must not hide the other, and neither may block
    teardown (an agent that cannot report must still not outlive its bounds)."""
    problems = []
    text = report_text(rec)
    try:
        persist_event(to=rec["administrator"], frm=rec["name"], reason=RESULT_REASON,
                      rose=False, item=rec["item"], item_status=None,
                      detail=text[:600], key=f"ephemeral:{rec['name']}:result")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"administrator event NOT written ({type(exc).__name__})")
    try:
        comment(rec["item"], text)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"item comment NOT written ({type(exc).__name__}: {str(exc)[:120]})")
    return problems


def _git(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60)


def worktree_holds_work(dest: Path, base: str = "origin/main", git=_git) -> bool:
    """Any tracked change, any untracked path that is not the launcher's kit,
    or any commit past base is the agent's output: keep it. Uncertain = keep."""
    status = git("-C", str(dest), "status", "--porcelain")
    if status.returncode != 0:
        return True
    for line in status.stdout.splitlines():
        if not line.startswith("?? "):
            return True
        top = line[3:].strip().strip('"').split("/", 1)[0]
        if top not in KIT_PATHS:
            return True
    ahead = git("-C", str(dest), "rev-list", "--count", f"{base}..HEAD")
    return ahead.returncode != 0 or ahead.stdout.strip() not in ("0", "")


def remove_workspace(rec: dict, root, git=_git) -> str:
    """'removed', 'kept (holds work)' or 'none'. Never discards output."""
    ws = rec.get("workspace")
    if not ws or not Path(ws).exists():
        return "none"
    dest = Path(ws)
    shared = rec.get("worktree_of")
    if not shared:
        scratch = ledger_dir(root) / "scratch"
        if scratch in dest.parents:
            shutil.rmtree(dest, ignore_errors=True)
            return "removed"
        return "kept (not st's scratch)"
    if dest.is_symlink():
        return f"kept (symlink): {dest}"
    common = git('-C', str(dest), 'rev-parse', '--path-format=absolute', '--git-common-dir')
    source = git('-C', str(shared), 'rev-parse', '--path-format=absolute', '--git-common-dir')
    branch = git('-C', str(dest), 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if (common.returncode or source.returncode or branch.returncode
            or not common.stdout.strip() or not source.stdout.strip()
            or Path(common.stdout.strip()).resolve() != Path(source.stdout.strip()).resolve()
            or branch.stdout.strip() != f"wt/{rec['name']}"):
        return f"kept (worktree identity uncertain or branch changed): {dest}"
    if worktree_holds_work(dest, git=git):
        return f"kept (holds work): {dest}"
    r = git("-C", shared, "worktree", "remove", "--force", str(dest))
    if r.returncode != 0:
        return f"kept (git worktree remove failed: {(r.stderr or '').strip()[:120]})"
    git("-C", shared, "branch", "-D", f"wt/{rec['name']}")
    return "removed"


def _try_remove_workspace(rec: dict, root, git=_git) -> str:
    try:
        return remove_workspace(rec, root, git=git)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"kept (cleanup uncertain: {type(exc).__name__}): {rec.get('workspace')}"


def teardown(root, name: str, *, kill_session, git=_git, now: float | None = None) -> dict:
    """Card first, then pane, then worktree. In that order so a tend pass that
    lands mid-teardown finds no card for the dead pane and cannot respawn it."""
    rec = read(root, name)
    if rec is None:
        raise Refused(f"no ledger entry for {name}")
    if 'uid_binding' in rec:
        from . import job_launch
        # No pane/tree observation can establish termination of a separate UID.
        # Preserve card, lane/cap, workspace and ENDING state on any uncertainty.
        try:
            job_launch.stop(root, rec)
        except (job_launch.IdentityError, OSError, subprocess.SubprocessError) as error:
            raise Refused('job UID termination unproven; lane retained: ' + type(error).__name__) from None
    card = Path(root) / "crew" / f"{name}.json"
    try:
        card.unlink()
    except FileNotFoundError:
        pass
    # st's own per-agent runtime state (the published plate) under crew/<name>/.
    shutil.rmtree(Path(root) / "crew" / name, ignore_errors=True)
    try:
        kill_session(f"st-{name}")
    except Exception:  # noqa: BLE001 — an already-dead session is the goal state
        pass
    # A provisioner may have held the ledger lock while the pane was killed.
    # Re-read AFTER that lock is released: never overwrite its new destinations
    # with the stale spawn record read at the beginning of teardown.
    with lock(root):
        rec = read(root, name)
        rec["workspace_teardown"] = _try_remove_workspace(rec, root, git=git)
        results = []
        seen = {str(Path(rec['workspace']).resolve())} if rec.get('workspace') else set()
        for entry in rec.get('worktrees', []):
            dest = str(Path(entry['workspace']).resolve())
            if dest in seen:
                continue
            seen.add(dest)
            owned = dict(entry, name=name)
            results.append(dict(entry, result=_try_remove_workspace(owned, root, git=git)))
        rec['worktree_teardowns'] = results
        rec["state"] = DONE
        rec["torn_down_at"] = time.time() if now is None else now
        write(root, rec)
    return rec


def finish(root, name: str, verdict: str, summary: str, cause: str, *,
           persist_event, comment, schedule_teardown, now: float) -> tuple[dict, list[str]]:
    rec = record_result(root, name, verdict, summary, cause, now)
    problems = notify(rec, persist_event=persist_event, comment=comment)
    schedule_teardown(name)
    return rec, problems


def detached_teardown(root, name: str, delay: float = 2.0) -> None:
    """Teardown from INSIDE the agent's own pane kills the process running it,
    so it runs in its own session, after this command has printed and exited."""
    subprocess.Popen([sys.executable, "-m", "shantytown.ephemeral", "teardown",
                      "--root", str(root), "--delay", str(delay), name],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- the reaper (code-side, run by `st fleet tend`) ---------------------------

def reap(root, *, pane_alive, end, now: float, dry_run: bool = False) -> list[str]:
    """End every live job whose pane is gone or whose deadline passed, and finish
    any teardown a crash left half-done. Returns one line per action."""
    out = []
    for rec in live(root):
        name = rec["name"]
        if rec["state"] == ENDING:
            out.append(f"{name}: finishing interrupted teardown")
            if not dry_run:
                end(name, None, None)
            continue
        launching = (rec["state"] == LAUNCHING
                     and now - rec.get("spawned_at", 0) < LAUNCH_GRACE_S)
        cause = ("timeout" if now >= rec["deadline"]
                 else "" if launching or pane_alive(f"st-{name}") else "died")
        if not cause:
            continue
        out.append(f"{name}: {cause} -> reported to {rec['administrator']}, torn down")
        if not dry_run:
            end(name, "failed", cause)
    return out


# --- views --------------------------------------------------------------------

def _left(rec, now) -> str:
    left = int((rec["deadline"] - now) // 60)
    return f"{left}m left" if left >= 0 else f"{-left}m OVER"


def render(recs: list[dict], now: float, *, recent: int = 5) -> list[str]:
    """Lines for `st agent spawn --list`, `st crew` and the admin's anchor."""
    lines = []
    running = [r for r in recs if r.get("state") in (LAUNCHING, LIVE, ENDING)]
    for r in running:
        target = f" {r['repo']}#{r['pr']}" if r.get("pr") else ""
        lines.append(f"{r['name']:<20} {r['job']:<7} {r['item']}{target} · {r['harness']} · "
                     f"{r['state']} · turn {r.get('turns', 0)}/{r['max_turns']} · {_left(r, now)}")
    done = sorted((r for r in recs if r.get("state") == DONE),
                  key=lambda r: r.get("ended_at") or 0, reverse=True)[:recent]
    for r in done:
        res = r.get("result") or {}
        lines.append(f"{r['name']:<20} {r['job']:<7} {r['item']} · ended {res.get('verdict', '?')}"
                     f" ({res.get('cause', '?')}) · worktree {r.get('workspace_teardown', '?')}")
    return lines


def summary_line(root, now: float | None = None) -> str:
    running = live(root)
    if not running:
        return ""
    now = time.time() if now is None else now
    return (f"{len(running)} ephemeral job(s) live: "
            + ", ".join(f"{r['name']} ({r['job']} {r['item']}, {_left(r, now)})"
                        for r in running)
            + " — `st agent spawn --list|--stop|--retry`")


# --- plumbing entry: `python -m shantytown.ephemeral teardown` ----------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m shantytown.ephemeral")
    ap.add_argument("mode", choices=["teardown"])
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("name")
    a = ap.parse_args(argv)
    if a.delay:
        time.sleep(a.delay)
    from .tmux import Tmux, declared_socket
    panes = Tmux(socket=declared_socket(a.root))
    teardown(a.root, a.name, kill_session=panes.kill_session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
