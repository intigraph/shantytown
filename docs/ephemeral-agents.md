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

### Review-to-enqueue custody (offline library)

`review_enqueue.Store` is the first part of the deterministic review handoff.
It is not connected to reporting, recruitment or a forge mutation. Existing
merge-job behavior remains in place until the whole handoff is qualified.

The controller must provision `<root>/ephemeral/review-enqueue` as its own
private directory, outside the job UID's writable ancestry. Only a controller
may supply the configured root and forge authority, protected job specification
and UID-validated report. The store independently verifies the enrolled,
signed exact-head APPROVE through `job_review.confirmed` before retaining an
intent. An intent pins authority, repository, PR node/number, head, reviewer,
signer, graph and review record. Repeated delivery returns that same intent;
job teardown does not remove it.

An intent starts `pending`. `begin` durably consumes one attempt before a
future native adapter may mutate the remote; `finish` records `queued`,
`refused` or `unknown` with its matching attempt token and receipt reference.
A crash in `attempting`, an unknown result or a terminal refusal cannot reset
to pending. Reconciliation is a separate operation; there is no automatic
retry, cleanup or repair. Prepared files left by a crash block new custody
until operator reconciliation. Capacity failure preserves existing evidence.

Custody proves past review verification, not permission to merge. Native
receipt compatibility, fresh revocation/head/CI checks, the shared
versioned per-service order/hold gate across every admission producer, and a
real approve-to-merge acceptance are still prerequisites for enabling this
handoff or retiring merge recruitment. This library supplies no enqueue
command, scheduler, signing-key enrollment or activation flag.

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
| `triage` | claude | Find the cause of a red check. Comment the diagnosis on the item. Attended jobs may propose a fix on a branch and PR, never onto main. Protected UID jobs receive the read-only alert-triage instructions below. |

Protected triage jobs (a controller ledger record with `uid_binding`) investigate
one alert and report once on its original item, then exit. Their instructions
forbid ACKs, silences, restarts, configuration or code changes, publication, and
other runtime actions. Missing evidence or access produces a blocked report;
the job never borrows the controller's credentials. This narrower prompt does
not establish OS or endpoint capability isolation. Protected delivery, own-key
permissions, native negative probes, and host admission remain prerequisites
before enabling unattended launches. This change does not enable that gate.
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

The staged helper's fixed `prepare <principal> <digest>` operation builds that
minimal store only for its admitted controller UID and exact protected slot
manifest. It creates one public own-job card and a configuration with verified
identity required, zero spawn capacity, unattended admission disabled and UID
readiness false. No controller config, pane, credential, endpoint or signing key
is copied. Existing stores must match exactly; extra or changed files refuse.
Interrupted staging is retained for explicit recovery. Preparation does not
consume a launch slot, create an account or launch a job. Provisioning must grant
this exact operation separately; a job's submit-only rule never grants prepare.

Protected job stop hooks authenticate their UID before consulting environment
identity or controller pane/hold state. They submit a bounded own-turn receipt;
context depth is unknown when no own measurement is available. Failed identity
or receipt acknowledgement blocks further work. The controller remains the
budget and teardown authority. Launch rechecks the job's own attestation after
admission and before consuming its UID reservation.

The separate helper bootstrap uses a fixed private Python with `-BIS`: isolated
imports, no environment/cwd/user-site paths, no site or `.pth` execution, and no
generated bytecode that would change the pinned runtime tree. It requires the
private interpreter prefix rather than a system-library fallback.
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

## Scoped event recruiter source qualification

`st agent spawn --recruiter --ephemeral --job review --repo OWNER/REPO --pr N
--item ID --head SHA --dry-run` qualifies a request through a separate capability;
it does not make the principal an administrator. `--json` returns a
`shantytown.recruitment-plan/v1` object with `live: false`. This is not a spawn
receipt. Live requests currently refuse before the protected launcher because
its sudo transport is outside the recruiter's granted authority. A reviewed
controller handoff is a separate prerequisite; no fallback is provided.

The authenticated principal and UID come from protected identity configuration
and its existing introducer enrollment. A fixed protected `recruiters.json`
selects the permitted root, host, repositories and jobs. For example, an
operator policy can use principal `crew-recruiter`, UID 10001, an isolated
private home `/var/lib/shantytown/agents/crew-recruiter`, and the configured
crew host. Those values are not compiled into the authorizer. This source does
not create the user, enroll its key, install identity policy or enable a drain.
The recruiter's UID and a launched job's UID must be distinct. It receives no
administrator credential, sudo grant or controller socket.

The policy structure is `{"version":1,"principals":{"PRINCIPAL":{"uid":10001,
"root":"/absolute/crew/root","host":"configured-host","repos":["intigraph/widget"],
"jobs":["review"]}}}`. The file and its parent chain must be operator-owned and
non-writable by other users. Missing/malformed identity or scope, wrong UID,
root or host, extra command overrides, and all merge requests refuse.

Custody is only the native `chaski.github.work-request/v1` record read by the
existing helper from the exact item's description. Repository, PR number, job
and revision must match. PR prose, branches, trailers, comments and webhook
payloads establish no custody. The legacy record is deliberately reused;
introducing a stronger signed custody format is a separate schema change.

Qualification reads authoritative current PR state, bounded complete check and
status inventories, required contexts/app identities, and verified non-author
verdict state from the configured verdict graph. Unknown author/verdict state,
partial inventories, outside contributors, existing verdicts, changed custody
or a changed head refuse. The ordinary cap, protected job UID, hold and governor
checks remain in the source path. Merge recruitment remains disabled.

[Source demonstration](demos/scoped-recruiter/README.md) uses explicit fake
identity/forge adapters and no live job. Operational acceptance still requires
the separately authorized security migration, controller transport and a real
event-triggered review with durable receipt and latency measurement.

### Signed recruiter request qualification

`recruit_request.py` qualifies a bounded, domain-separated
`shantytown.recruitment-request/v1` envelope offline. Its fixed fields admit
only review launch or review stop; merge, arbitrary argv, environment, paths
and request-supplied keys are refused. Ed25519 verification uses the declared runtime dependency
`cryptography>=46,<47` and still refuses if it is unavailable. Source metadata
does not prove that an installed controller has the dependency or a key binding.

Authenticated requests expire within 120 seconds. A durable unique nonce is
reserved before exact native custody lookup, so a crash or custody refusal
cannot turn into an automatic replay. Refusals retain fixed reason labels,
without exception text or key material. The supplied `Binding` is an offline
fixture input, not proof of root-owned policy or introducer enrollment.

The read-only source loader checks the fixed root-owned controller key file
against the unique UID/principal in protected `identity.json`, with configured
host/root/repository validation. Installing that binding and proving introducer
enrollment remain activation work. Controller source qualification below integrates
fresh forge/check/verdict admission and stop-target ownership checks. Protected
persistent nonce state, live handoff and the separate activation/rollback approval
remain prerequisites before the first live signed request. Live recruiter
requests remain refused before native selection.

The proposed controller binding file is `/etc/shantytown/recruit-controller.json`,
with exactly `version`, `principal`, `uid`, `host`, `root`, `repos`, and
`public_key` (32-byte Ed25519 public key in lowercase hex). Neither this file
nor `identity.json` may have writable or symlinked parent components. Duplicate
JSON keys are refused. This is configuration read by the existing controller,
not a receiver service; no key file is installed by this PR.

The future live integration has one seam: the scoped-recruiter refusal before
`uid_launch` / `job_launch`. Only reviewed transport may replace that refusal
with `handoff(envelope) -> receipt`, retaining the receipt in `rec['recruiter']`.
It must not bypass the existing planner, admission or protected launcher gates.
For now the refusal remains. Root-pinned key reads reuse
`advise_signing._read(..., owner=0)` (also used by verdict signer pins), with
protected parent validation added; graph trust alone never supplies the key.

### Existing controller signed-request preview

`st agent spawn --recruitment-request --dry-run --json` reads one signed
envelope from stdin, ending at EOF (8 KiB and a five-second pipe deadline).
Only an independently authenticated controller administrator can use it.
Mixed CLI selectors, a recruiter acting as its own controller, a different
configured host/root, duplicate JSON keys and malformed or oversized frames
are refused. The request never selects the root-owned key or controller path.

`recruit_controller.receive` checks protected enrollment, request signatures,
expiry and nonce reservation before the existing fresh admission adapter.
Review launch rechecks the exact native item description, PR head, complete
checks and authoritative non-author verdict state. Review stop instead
requires the controller's own live job ledger to match the recruiter's exact
principal, host, item, repository, PR, head and distinct protected job UID.
Stop does not require green checks: a failed job must remain stoppable.
Custody and expiry are checked again after the reads; a slow read never extends
the signed lease. Refused or interrupted authenticated attempts remain spent
in the supplied ledger; durable fixture tests reopen it to verify refusal.

The CLI preview uses an **in-memory ledger**, so it writes no production state
and grants no durable replay protection or operational acceptance. Its receipt
always says `live: false`, `execution: refused`, `durable_acceptance: false`.
It contains a canonical request digest, not the signature or nonce. There is
no execution callback, listener, socket, service, enrollment or privileged
call. Without `--dry-run` the command refuses before reading stdin or keys.
The recruiter's existing live-refusal seam is unchanged. Live integration must
add reviewed protected persistent state and transport, then re-enter the normal
planner, holds, governor, cap and protected launcher gates; a preview receipt
is never a credential for skipping those checks. Merge verbs remain excluded.

### Protected nonce state and launch admission handoff

`recruit_store.Store` and `recruit_handoff.prepare` provide the next controller
library slice. Merge permitted; runtime activation gated separately. The CLI
preview still uses memory and the live-refusal seam remains in place. Neither
library is a new listener or a route to the privileged launcher.

The protected controller binding supplies the root. A provisioner must create
`<root>/ephemeral/recruitment` owned by the controller with mode `0700`; the
library never creates missing parents. The state file name is fixed. Directory
FD traversal refuses links, foreign owners and group/world-writable ancestors.
Files require controller ownership, mode `0600`, one link and a regular inode;
unknown entries, corrupt/incomplete databases and unexpected schemas refuse.
The qualified backend is Linux, using a pinned directory-FD path for SQLite and
its journal. Other platforms refuse this backend rather than using a weaker
path. Tests explicitly model trusted outer fixture ancestry; production has no
fixture exception.

SQLite uses DELETE journals and synchronous EXTRA, including directory sync
after journal removal. The database is bounded to 64 MiB, 50,000 nonces and
operations, and 200,000 audit rows. Capacity, corruption or an interrupted
initialization require operator disposition; records are never automatically
pruned, reset or replaced. Source rollback retains this state. Reservations,
operation claims, refusals and prepared observations survive process exit.
Fresh nonces cannot repeat a launch candidate for the same repo/PR/head/job.

The handoff first reuses signature, expiry and fresh exact-head authority
checks. Fields are detached from caller memory using the exact canonical bytes
covered by the signature before authority callbacks. It then durably claims the
candidate and enters the existing ephemeral lock, planner, cap, protected job
selector and governor interfaces. Quiet-time uncertainty and maintenance windows
refuse; malformed job inventory cannot appear as free capacity. Recruiter,
controller and review job identities must differ. Custody, expiry and the exact
unused protected capability are checked again after the gates. A refusal or
interruption spends the attempt; an unknown reply is not automatically replayed.

The resulting receipt reports a durable nonce and prepared plan digest, with
`live: false`, `execution: refused`, `activation: gated`. Preparation reserves no
runtime cap and proves no native UID drop. It creates no job/card/pane, invokes
no sudo or execution callback, and cannot be reused as a launch credential.
Runtime execution must re-enter the normal launcher and its current gates after
separate activation qualification. Stop still uses the earlier non-executable
preview; this handoff accepts review launch only. Merge verbs remain excluded.

### Controller durable preparation entry

`st agent spawn --recruitment-prepare --dry-run --json` accepts one signed
stdin frame using the existing bounded reader. This is an independent verified
controller operation, never a recruiter privilege. It enters the protected
persistent handoff library using the configured administrator, unattended
policy, native custody reader and existing governor adapter. Mixed request
selectors and an in-job identity refuse before stdin is read.

The explicit preparation mode **writes durable nonce/audit/operation state**;
`--dry-run` guarantees no launch, not a read-only database preview. Replaying
that signed frame, even after reopening the database, refuses. It never creates
state directories or enables a missing capability. Use the earlier
`--recruitment-request --dry-run` for the memory-only preview instead.

The resulting receipt remains `live: false`, `execution: refused`,
`activation: gated`. No transport listener or protected execution callback is
installed. Runtime activation remains gated on xu2; merge verbs are excluded.

## Watch evidence evaluator (source interface)

`shantytown.watch_program` validates immutable program data and evaluates
qualified samples without I/O, launch, signing, compensation or item closure.
It is not a long-running ephemeral agent or a second scheduler. Both future
selected-source adapters must call `WatchSpec.validate`; there is no TOML or
Quipu loader or fallback in this module.

The source schema contains version, run ID, selected-source SHA256, native
deployment receipt, frozen component identity, original start/window/cadence,
and named finite nonnegative upper limits. The sample grid always includes
the original end, even if cadence does not divide the window. Resuming uses
that same grid. Missing, duplicate, reordered, nonfinite or future samples
cannot pass, and a changed identity supersedes the run. An incomplete ended
window is UNKNOWN. A measured bound breach survives another missing metric.

The result separates safety, native activation and improvement. Configuration
true is not an activation input. An inactive capability can have a safe watch,
while improvement stays NOT_EVALUATED. An active capability needs positive,
finite, admitted comparable before/after cohorts; a flat result is explicitly
NO_IMPROVEMENT. Compensation always remains NOT_EXECUTED here.

A controller must authenticate the reader evidence and deployment/authority
receipts before calling this pure evaluator. Its strings and hashes do not
authenticate a caller. Managed-unit collection, durable evidence, callbacks,
signed non-review results and the shared Action executor remain separate
integration gates. This source interface does not satisfy live watch acceptance.
