# Ephemeral agents

`st agent spawn --ephemeral` starts a short-lived, supervised agent for one job:
review a PR, merge a PR, triage a red CI run, or do one small task. The
administrator manages these agents, and they report back to it. This is step 3
of the GitHub → quipu → chaski → st pipeline (aegis-c01c). chaski's routing
rules call this command; the administrator can also run it by hand.

## Why polecats were retired, and what is different here

Gas Town had ephemeral workers ("polecats"). They were retired under the
CREW-ONLY rule, partly because a spawned worker could escape supervision. It
could outlive its job, spend without limit, merge on its own authority, or
disappear without anyone being told. Each rule below closes one of those gaps.

| Gap                         | Rule here |
|-----------------------------|-----------|
| No owner                    | The card's `reports_to` is the administrator, and only the administrator (or a human shell) may spawn, stop or retry. An ephemeral agent can never spawn another one. |
| Unbounded life              | Every job has a deadline (`lifetime_minutes`). The agent's Stop hook and every `st fleet tend` pass enforce it. Neither one is an agent poll. |
| Unbounded spend             | A turn budget (`max_turns`) and a context budget (`max_context_k`) are checked at every Stop. The agent counts in the usage governor like any card and carries the `first` survival band, so a governor tier sheds it first. |
| Unbounded fan-out           | `max_agents` caps how many ephemeral agents can be live on a host at once. The fleet governor's lane cap and its tier exclusions apply too. Over cap means **refused**, never queued in secret. |
| Silent exit                 | Every ending writes a result to the ledger, comments on the work item and sends one stop event to the administrator. That includes a clean report, a timeout, a budget hit, a dead pane and a manual stop. The event is keyed, so a retried report is never sent twice. |
| Respawned zombies           | `st fleet tend` never respawns an ephemeral card. When the pane is dead or past its deadline, tend reaps it instead. |
| Mistaken for crew capacity  | Rule Zero / `free_feedable_workers` skip ephemeral cards, so a coordinator is never told to dispatch board work to one. |
| Merging around the lane     | A merge job holds its repo's serialized merge lane for its whole life: one merge job per repo at a time, with `merge_spacing_minutes` between them. Its prompt forbids a direct push, an admin override and a branch-protection bypass. It may only merge with `--match-head-commit` after it has checked CI and a non-author review. |

## Lifecycle

```
spawn ─► admit (authority, cap, governor, merge lane) ─► ledger "live" + card
      ─► worktree (st repo worktree machinery, own branch) ─► _launch (the ONE launcher)
      ─► job prompt delivered as the verified startup turn
      ─► agent works … each Stop: turn/context/deadline check
      ─► `st agent spawn --report --verdict V --summary S`
            (or deadline / budget / dead pane / --stop)
      ─► result: ledger + item comment + stop event to the administrator
      ─► teardown: card removed, tmux session killed, worktree removed iff unchanged
```

The ledger lives at `<root>/ephemeral/<name>.json` and is the source of truth.
The card in `<root>/crew/<name>.json` is an ordinary worker card, so the census,
the governor, `st crew` and the launch path all see the agent with no special
cases. Teardown deletes the card **before** it kills the pane, so a tend pass
can never find a dead pane with a live card and respawn it. A worktree that
holds commits or uncommitted changes is **kept**, and the result says so,
because discarding an agent's output is the data-loss class `cleanup_worktree`
exists to refuse.

Names are generated as `eph-<job>-<6 hex>`. Each agent has its own worktree on
branch `wt/<name>` when `--repo` names a checkout. Without `--repo` it gets a
scratch directory under the ledger.

## Jobs

| Job      | Default harness | Prompt contract |
|----------|-----------------|-----------------|
| `review` | codex (fleet directive: reviews on codex) | Independent, non-author review of `--repo/--pr` at the exact head. Post one verdict comment on the PR (APPROVE / REQUEST CHANGES with findings). Never push, never merge. |
| `merge`  | claude | Only through the serialized lane. Verify green CI and a non-author approving review at the exact head, then merge with `--match-head-commit`. Never push to the base branch, never `--admin`, never bypass protection. If anything is unproven, report `blocked`. |
| `triage` | claude | Find the cause of a red check. Comment the diagnosis on the item. A fix goes on a branch and PR, never onto main. |
| `task`   | claude | Do the item's acceptance criteria in the worktree. Open a PR if code changed. |

`--harness` overrides the default. `[ephemeral.harness_by_job]` changes the
defaults per deployment.

## Administrator surface

```
st agent spawn --ephemeral --job review --item aegis-x --repo owner/name --pr 12 [--checkout PATH]
st agent spawn --list [--json]          # live + recent jobs (also in `st crew` and the admin's `st anchor`)
st agent spawn --stop eph-review-1a2b3c # result "stopped", report, teardown
st agent spawn --retry eph-review-1a2b3c   # new agent, same job, attempt+1 (max 3)
st agent spawn --report --verdict approve --summary-file -   # run BY the ephemeral agent
st agent spawn --reap                   # the sweep tend runs; by hand for a dry look with -n
```

## Configuration

```toml
[ephemeral]
max_agents = 2              # live ephemeral agents per host; 0 disables spawning
lifetime_minutes = 60       # hard deadline per job
max_turns = 40              # Stop-hook turns before the budget ends the job
max_context_k = 300         # context ceiling in k tokens
merge_spacing_minutes = 10  # minimum gap between merge jobs on one repo
unattended = true           # launch without approval prompts; default: the administrator card's setting

[ephemeral.harness_by_job]
review = "codex"
```

## Out of scope here

GitHub ingress (aegis-c01c.3), the chaski routing rules that decide *when* to
spawn (aegis-c01c.4), the stop-policy change that counts the administrator's
in-flight ephemeral work (aegis-c01c.1), and the tambo install/verify step
(aegis-c01c.5).
