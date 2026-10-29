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
| No owner                    | The card's `reports_to` is the administrator, and only the administrator (or a human shell) may spawn, stop or retry. An ephemeral agent cannot spawn another one. The check does not depend on `$SHANTY_AGENT`, which a pane can unset: a process whose working directory is inside a live job's workspace, or that descends from a job's tmux pane shell, *is* that job. |
| Unbounded life              | Every job has a deadline (`lifetime_minutes`). The agent's Stop hook and every `st fleet tend` pass enforce it. Neither one is an agent poll. |
| Unbounded spend             | A turn budget (`max_turns`) and a context budget (`max_context_k`) are checked at every Stop. The agent counts in the usage governor like any card and carries the `first` survival band, so a governor tier sheds it first. |
| Unbounded fan-out           | `max_agents` caps how many ephemeral agents can be live on a host at once. The fleet governor's lane cap and its tier exclusions apply too. Over cap means **refused**, never queued in secret. |
| Silent exit                 | Every ending writes a result to the ledger, comments on the work item and sends one `ephemeral-result` event to the administrator. That includes a clean report, a timeout, a budget hit, a dead pane, an undelivered job and a manual stop. The event is keyed, so a retried report is never sent twice. The administrator's drain renders it as a **finished job** (verdict + item), never as a stopped crew member to re-dispatch. An ephemeral agent's per-turn stops send no crew stop event at all. |
| Unfed panes                 | The job prompt is the agent's verified first turn. On macOS, hook verification is always "cannot tell" because there is no `/proc`, so an ephemeral job is delivered anyway; the deadline does not depend on hooks. Delivered means the job's turn STARTED, not that its text landed: on Claude Code st checks the composer is empty, types the job with no Enter, waits to see it in the box (a long job shows as `[Pasted text #1 +N lines]`), presses Enter as its own keystroke and waits to see the turn start (busy marker, spinner, context-left drop or the job echoed). It presses Enter again, up to three times, only while the box holds just the job, and never on text it did not type. A pane whose job did not start is ended at once as `launch failed`, with the reason. |
| Respawned zombies           | `st fleet tend` never respawns an ephemeral card. When the pane is dead or past its deadline, tend reaps it instead. The reap runs first in every tend pass, before any early return for a hold or a registry error. A job is `launching` until its job is delivered; tend leaves a launching job with no pane alone for `LAUNCH_GRACE_S` (10 min), so a pass mid-spawn cannot orphan the pane. |
| Mistaken for crew capacity  | Rule Zero / `free_feedable_workers` skip ephemeral cards, so a coordinator is never told to dispatch board work to one. |
| Merging around the lane     | A merge job holds its repo's serialized merge lane for its whole life: one merge job per repo at a time, with `merge_spacing_minutes` between them. It merges only through `st agent spawn --merge --head SHA`. That command checks in code, against fresh forge reads, that the caller is a live merge job (review, triage and task jobs are refused) and that the PR is its own. It also checks that the head equals the verified SHA and the head the item pins, the PR is not a draft, the author is crew (never an outside contribution), there is a non-author approval on that head (a GitHub APPROVE, or a signed Quipu verdict record from an agent other than the author agent; see [Signed verdicts](#signed-verdicts-one-github-account)) and no outstanding change request, and every check run is green. Only then does it call `gh pr merge --match-head-commit`. The agent's own gh credentials remain the residual gap. |

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

Worktrees provisioned later by `st repo worktree` or `st go --worktree` for an
active job are recorded in its ledger before creation. Teardown checks these
alongside the spawn workspace, once per destination. Clean trees on the job's
original branch are removed; tracked changes, untracked output, ahead commits,
a changed branch or an uncertain Git identity keep the tree. Per-tree outcomes
are retained in `worktree_teardowns`. Provisioning after a job ends is refused.

Names are generated as `eph-<job>-<6 hex>`. Each agent has its own worktree on
branch `wt/<name>` when `--repo` names a checkout. Without `--repo` it gets a
scratch directory under the ledger.

## Jobs

| Job      | Default harness | Prompt contract |
|----------|-----------------|-----------------|
| `review` | codex (fleet directive: reviews on codex) | Independent, non-author review of `--repo/--pr` at the exact head. Post one verdict comment on the PR (APPROVE / REQUEST CHANGES with findings), then `--report --verdict V --head SHA --evidence URL`; st signs the verdict into Quipu. Never push, never merge. |
| `merge`  | claude | Only through the serialized lane, and only the head the item pins (`--head`, or the `revision` of the chaski work request in the item). Verify green CI and a non-author approval at that head, then merge through `st agent spawn --merge --head SHA`. Never push to the base branch, never `--admin`, never bypass protection. If anything is unproven, report `blocked`. |
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
st agent spawn --ephemeral --job merge --item aegis-y --repo owner/name --pr 12 [--head SHA]
st agent spawn --report --verdict approve --summary-file -   # run BY the ephemeral agent
st agent spawn --report --verdict approve --head SHA --evidence URL --summary-file -   # a review job
st agent spawn --merge --head <sha>     # run BY a merge job: the guarded merge
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
unattended = false          # keep approval prompts; omission inherits the administrator card
require_verified_identity = false # opt in after protected UID migration
unattended_uid_ready = false # unattended gate: OFF until distinct job UID isolation is verified

# Signed review verdicts (aegis-c01c.7). All empty = off.
verdict_graph = ""          # registered Quipu graph IRI the records go into
verdict_signer = ""         # verifier key id; default st-review.<host>
verdict_key = ""            # default $XDG_STATE_HOME/shantytown/verdict-signer.pk8
lane_release = []           # e.g. ["chaski-github-work", "--config", "/etc/chaski/github-routing.yaml"]

[ephemeral.harness_by_job]
review = "codex"
```

`require_verified_identity` defaults to false while hosts migrate. In this
compatibility mode, an administrator's environment identity or a human shell
can manage jobs, and report/merge retain the existing workspace/ancestry and
matching environment checks. A job in its workspace or process tree remains
unable to manage other jobs even after clearing its environment identity.
This mode retains the session-detachment limitation of the old guards.

After the host has protected UID bindings, set `require_verified_identity = true`.
Then spawn, retry, stop/reap (including merge-lane release), report and merge
require the protected identity described in
[agent identity migration](agent-identity-migration.md). Environment and
anonymous fallbacks are refused. Report/merge require the authenticated job's
own identity, independent of cwd/ancestry. Read-only `--list` remains available.
An existing policy's authentication errors still fail closed in either mode;
this setting does not bypass a broken or mismatching protected binding.

The `unattended_uid_ready` flag is an operator readiness declaration, not a UID
installer or proof of isolation. Keep it false pending the distinct-job-UID
migration decision and verification. `unattended = true` or an inherited
dangerous administrator card alone cannot enable unattended jobs. Gate refusal
happens before a retry ends the old job or writes a new ledger/card/worktree.
This change creates no users and changes no system policy or host configuration.
The trusted code-side tend reaper can still finish expired jobs.

## Signed verdicts (one GitHub account)

Every crew PR and every review comes from one shared GitHub account, so a
non-author GitHub APPROVE never exists. The approval lives in Quipu instead,
as the record chaski #49 routes on (`shantytown/gate_verdict.py`):

- **Review job.** `st agent spawn --report --verdict approve|request-changes
  --head SHA --evidence URL` (the process must be the review job) writes an
  `aegis:GateApproval`: `aboutGitHubEntity` (the PR node `aegis:github.<node_id>`),
  `commitSha`, `outcome` (approve / changes), `by` (the job's agent name),
  `recordedAt`, `authorAgent` (from the PR's `authoredByAgent` fact),
  `evidence`, `evidenceHash`. Beside it goes an `aegis:Verdict` whose
  `targetRef` is that record, signed with quipu's v1 verdict signature
  (ed25519 over `v1|predicate|target|outcome|evidence_hash|tier|verifier`,
  quipu `src/signing.rs`). The evidence hash covers every GateApproval field,
  so an edit after signing voids it. A failed write is reported, never
  silent, and no merge can rest on that review.
- **Merge gate.** `st agent spawn --merge` reads the records on exactly the
  head, from the ONE configured `verdict_graph` (never any named graph), and
  recomputes each evidence hash. A record counts only if its signature
  verifies under a key pinned in `/etc/shantytown/verdict-signers.json`
  (root-owned, not writable by others; `{"version": 1, "signers": {"<signer
  id>": "<public key hex>"}}`), the signer id is not an agent of the PR, AND
  Quipu's `POST /verdict/verify` with the stored verdict's IRI says `trusted`.
  Quipu alone is not enough: any agent can currently write a
  `VerifierRegistration` and enroll its own key. Then
  chaski's rules: a verdict by the PR's author agent never counts, each other
  agent's latest word counts, any `changes` blocks, an unknown author agent
  approves nothing. An unsigned or forged record is ignored. A Quipu read
  failure is "not approved".
- **Merge job.** It merges only the head its item pins. When it ends without
  merging, its lane frees at once (spacing counts merges only) and, if
  `lane_release` is set, st calls chaski's `lane release` with the request id.
- **Authorship.** `st repo pr --create` records `<PR> aegis:authoredByAgent
  "<agent>"` so chaski and the gate can tell author from reviewer.

The signer is st on the host, not the agent: ephemeral agents get a new name
per spawn, so no human could register theirs. Key custody is quipu's v1
posture (a 0600 host file, generated on first use, untrusted until
registered), and the agent's Unix user can read it, the same residual gap as
its gh credentials.

**Enabling (not done here).** Register a committed graph for the records
and set `verdict_graph`. Run one review to generate the key, then have a human
pin its public key with sudo in `/etc/shantytown/verdict-signers.json` and
write an `aegis:VerifierRegistration` in ROOT (`aegis:verifier` = the signer
id, `aegis:publicKey` = the key's public half, `aegis:attests
"github-pr-gate-approval"`). Set `lane_release` when chaski's receiver runs.

## Known limits

- **One GitHub identity.** A non-author GitHub APPROVE can never exist, so the approval comes from a signed Quipu verdict record (above). Until verdict records are enabled and the signer is registered, merge jobs report `blocked`. That is the safe outcome.
- **OS isolation remains a prerequisite for unattended jobs.** Compatibility mode retains environment/ancestry restrictions and their detachment limitation. Opt-in verified identity survives session detachment. Shared Unix UIDs are not isolation; unattended launches stay gated until the separately governed distinct-UID setup is verified.
- **Shared settings.** A spawn never rewrites the shared role settings files. Only crew launches repair the StopFailure hook there.
- **Hooks on macOS.** Stop-hook enforcement of the turn and context budgets needs the deployed `st` in the agent's pane. The deadline is enforced by tend regardless.

## Out of scope here

GitHub ingress (aegis-c01c.3), the chaski routing rules that decide *when* to
spawn (aegis-c01c.4), the stop-policy change that counts the administrator's
in-flight ephemeral work (aegis-c01c.1), and the tambo install/verify step
(aegis-c01c.5).

## Protected job launch capabilities (source staging)

The distinct-UID launcher uses an operator-owned capability per job principal,
not a username supplied by a model. `/etc/shantytown/jobs` on Linux, or
`/Library/Application Support/Shantytown/jobs` on macOS, holds reviewed manifests.
Each binds the exact request, harness, controller UID, dedicated job UID/GID,
private home/workspace/settings and pinned argv. Controller environment and
arbitrary command arguments are never forwarded. The installed helper must be
root-owned, run an isolated interpreter from a private immutable installation,
and be the only executable named in its narrowly scoped sudoers rule.

The first account may be named `_stjobs`; additional principals require unique
accounts and UIDs. A shared or recycled UID cannot preserve distinct job
identities. Existing protected identity bindings require UID/GID >=10000; macOS
account hiding must use the explicit hidden-account attribute rather than
weakening that floor. Each job needs its own enrolled credentials. There is no
controller credential copy or automatic key registration.

A readiness boolean alone does not admit a launch. Verified identity and an
unused matching capability are required before retry side effects. A native
helper check validates the protected actor binding and actual account, checks
private state, and probes privilege dropping in a short disposable child. The
real launch rechecks its immutable manifest, reserves the UID in a locked,
fsynced receipt, clears supplementary groups and inherited file descriptors,
drops root credentials, and executes only the prepared argv with an allowlisted
environment. A failed drop never falls back to the controller UID. Receipts and
job homes survive failures and rollback; a UID is not reused for another job.

A live unattended retry currently refuses and preserves its old lane, even
following a successful probe. Completed retries require a fresh capability.
This avoids claiming an atomic cross-UID handoff from a preflight observation.
Attended compatibility behavior remains separate.

This source staging is **not installed acceptance**. Keep both readiness and
verified-identity activation at their existing deployment values until the
reviewed provisioning and native acceptance packet is complete. Cross-UID
reporting and turn accounting use a staged mediated mailbox described below:
do not make the shared ledger writable or expose controller signing keys.
Tambo/macOS and Goldblum/Linux source provisioning, isolated metadata/config,
own-key review signing, native file/signal/identity denial proofs and rollout
authority remain required before enabling unattended jobs.

The staged protected helper also has a fixed `stop <principal> <digest>`
operation for the admitted controller. It verifies the exact consumed UID
receipt, forks, drops to that UID, and signals remaining processes by UID,
including processes outside the original session. Signals never run as root.
An unreadable process table, failed drop, permission failure or timeout leaves
termination unproven. Teardown then retains the card, workspace and occupied
lane; a supplied DONE record cannot override the controller ledger. Native
macOS/Linux qualification of this operation is still required.

The read-only launch probe now also performs the existing pinned identity
attestation from the job's own home after UID drop and environment clearing.
It must return the registered job principal. A username or successful UID
switch alone does not establish readiness. These staged paths have only been
qualified with private source fixtures; no privileged helper was installed or
executed as part of that qualification.

Operator preparation must include a root-owned `slots.json` next to the job
manifests. Version 1 has exactly `version`, `uid_min`, `uid_max`, and `slots`.
The range must start at 10000 or higher; `slots` maps each exact job principal
to its reserved `uid` and manifest `sha256`. Its entry count is the explicit
host capacity, bounded to 1024 by the source parser. There is no default host
range or automatic account growth. The actual count/range belongs in the
reviewed per-host rollout packet.

The protected manifest set must exactly equal this plan. Missing, extra,
changed, duplicate-UID or shared-account entries refuse, including when the
helper is invoked directly. Consumed manifests and UID receipts remain as
non-reuse records after cleanup or rollback. Adding capacity or changing a
reservation requires a separate operator-reviewed plan update; exhaustion
never falls back to another UID. This implements the selected per-job slot
architecture, while unattended readiness remains false pending native proof.

The fixed helper's `submit` operation admits only the manifest's job UID;
`poll` admits only its controller UID. Both require the exact protected binding
and consumed UID receipt. Jobs submit a bounded JSON result or turn token on
stdin, with a five-second input deadline. They cannot select a ledger path,
another principal, a command, or a signing key. A root-private mailbox retains
the first result, deduplicates turn tokens, and refuses conflicting retries,
corruption, exhaustion or interrupted writes. Jobs never open the controller
ledger through this path.

The source report handler queues the message before reading controller config.
The turn hook queues a turn; the controller's existing reaper drains messages,
applies monotonically increasing turn counts and performs ordinary notification
and verified UID teardown. A queue acknowledgement means the message is saved;
delivery and teardown are still pending. Job reports confer no signing or
merge authority. Until the job's own review signer is qualified, an unsigned
review message becomes a blocked result; no controller key substitutes for it.
These paths are staged source with private fixture coverage, not native
cross-UID acceptance or an installed deployment.

A launch manifest has separate `controller_root` and `root` paths. The former
identifies the controller's private store; launch qualification requires its
path to belong only to root/the controller and its directory mode to exclude
other users. The latter must be the job's own root-owned metadata store at
`/var/lib/shantytown/job-stores/<principal>`. Only that job root is passed in
`SHANTY_ROOT`; the controller root is not forwarded to the job environment.
The two stores cannot contain one another. The provisioning packet must build
the minimal public job metadata there without controller secrets. Lifecycle
stop/drain authorization uses immutable identity and the consumed receipt,
so changing job-owned settings cannot prevent the controller from stopping it.

The separate helper bootstrap uses a fixed private Python with `-IS`: isolated
imports, no environment/cwd/user-site paths, and no site or `.pth` execution.
Before importing application code it validates its interpreter/import paths
and the entire bounded package at `/opt/shantytown-job-launcher/app/shantytown`
as root-owned and non-writable, refusing symlinks. The reviewed installation
must provide regular immutable interpreter/application paths; an editable
checkout or ordinary user-owned virtualenv is not a supported helper install.
The bootstrap keeps only sudo's kernel-derived caller UID and fixed PATH/locale
for application imports. Native installation qualification remains outstanding.

The capability path validator accepts macOS's fixed root-owned `/var` alias
only when it resolves to `/private/var`, whose immutable ownership is checked
as well. This permits the existing protected-home convention on macOS without
accepting job-controlled symlinks or arbitrary aliases. Native macOS acceptance
is still required; the source fixtures simulate both accepted and refused paths.

Protected review slots can declare an explicit `review` policy in their pinned
manifest; other slots use `review: null`. The policy names the exact repository,
PR number, GitHub node, reviewed head, author, graph, verifier ID, public key,
and the job's private key path. The verifier ID is
`st-job-verifier.<job-principal>`, with a distinct key per slot. The key must
already exist, be private to the job UID, and match the protected public key.
No controller key, environment-selected key, automatic key generation or
registration is used by this path.

Operator pin-file version 2 supports these scoped entries alongside legacy
host keys. A scoped entry has `public_key`, `principal`, `repo`, `pr`, `pr_node`,
`head`, and `author_agent`. Its signature counts only for that exact reviewer
and PR/head, with independently readable matching authorship. A bare job-key
pin or a key duplicated under another signer refuses. Version 1 retains the
legacy host behavior. Both the operator pin and Quipu's recorded trusted
signature are required; self-registration cannot widen local trust.

Before its single write, a job saves a private, fsynced prepared review record.
If the reply is lost, a retry reads back that same signed record; an unproved
effect is retained without automatic resend. The job queues only the record
reference, head and signer. The controller independently verifies that record
and scope before accepting an approval/change result, then performs ordinary
notification and UID teardown. A missing or unproved signature still becomes
blocked. No real signing identity or registration was created during source
qualification; per-job enrollment and native isolation remain rollout work.
