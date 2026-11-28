# Pushes and pull requests

`st repo push` and `st repo pr`: where a push may go, what a pull request is checked against and how merged work is recognized. This page is part of [the CLI reference](cli.md).

## PR overlap preflight

`st repo pr` earns a separate slot because it creates an external review object;
`repo context` remains a read. Use the guarded creation path after committing and
pushing the candidate branch. It requires the explicit GitHub repository to match
`origin`, with the mapped owner-move exception below. It does not push, merge,
close another PR, or activate native auto-merge.
Forgejo creation is not implemented by this command.

Candidate source must be committed and published. Untracked files may remain
only inside top-level `.work/` and `.task-notes/` directories. The preflight
checks the directory roots without following symlinks or reading private file
contents; these files do not enter the PR file list or metadata. A file or
symlink replacing either root refuses, as do unrelated untracked paths and every
tracked, staged, deleted, renamed or conflicted change, including under those
roots. No ignore/configuration change or force option is needed.

st's own job-worktree provisioning is also admitted (aegis-za4f.15): untracked
content under `.claude/`, `.agents/`, `.codex/` and `.bobbin/`, the untracked
regular files `.mcp.json` and `.shantytown-tooling.json`, and an unstaged
`AGENTS.md`/`CLAUDE.md` change confined to the `shantytown:tooling` block. An
edit outside that block, a staged instruction file, or any other path still
refuses.

The forge's canonical repository slug and stable ID are checked before creation.
A renamed slug refuses before POST and names the canonical slug; update the
requested repository and its matching origin deliberately, then run preflight
again. A legacy-owner `origin` can remain unchanged when the deployment's
`scripts/lib/stack_repos.py canonical` helper maps it to the requested current
slug **and** GitHub resolves it to that slug with the same stable repository ID.
The optional helper lives under
`${XDG_DATA_HOME:-~/.local/share}/aegis-exec-src/`; exact origins need no helper.
Missing, unreadable or unmapped policy, a foreign host/owner, an unproven redirect,
or a redirect race refuses before POST and names a concrete `git remote set-url`
fix. The requested repository must still be the forge's canonical slug.
This command never rewrites remotes or silently migrates aliases. A
repository identity change during preflight also refuses before POST. A lost or
malformed response after POST is first read back: one open PR for the candidate
head with the exact head and base SHAs is reported as created. Otherwise it
remains UNKNOWN (exit 2, `created: null`) and is reported on stderr as well as
JSON stdout. A 4xx rejection of the create (other than 408/429) is a definite
refusal. Inspect the canonical repository for the exact PR before retrying; the
command never automatically repeats a create. Every failed `gh api` call is named
in the refusal and in the JSON `github` field (call, exit, HTTP status, redacted
stderr). A branch GitHub does not have (404/422 on its commit) refuses as "push
the exact candidate branch", not as an unverified outcome. A task job that reports
`blocked` or `failed` pushes its `wt/<job>` branch first and says so in the report.

```sh
st repo pr example/project --checkout /path/to/own/worktree --bead project-abc
st repo pr example/project --checkout /path/to/own/worktree --bead project-abc \
  --create --title 'Concrete change' --body-file /tmp/pr-body.md \
  --dispositions-file /tmp/overlaps.json --dry-run
```

Omit `--create` for the open-PR overlap report. Both renamed paths and explicit
bead-family relationships count (`--bead-family project-epic` adds a parent).
Dotted child IDs share their root family. Drafts are included. Known release-plz,
release-please and ledger bot identities are excluded from overlap scans. Shared
GitHub Actions automation is excluded only on release or ledger branch patterns.
Release tools using a regular user token are recognized by a generated timestamped
release-plz branch paired with a release title, or a ledger branch paired with a
`chore(ledger):` title. A title or branch alone does not exclude human work.
These metadata classifications only suppress overlap advice, never authorize merge.

Overlaps are advisory: creation proceeds as a **draft**, with the overlapping PR
numbers, exact heads, shared files and item families in its body. No dispositions
file is required. Optional exact-head `stack`, `absorb` or `independent` annotations
are validated and appended when valid; missing, stale, invalid or unreadable
annotations produce advice rather than refusing creation. This command never
closes another PR based on overlap advice. Other-PR churn does not block creation.

Explicit body trailers declare publish lineage, one same-repository number per
line: `Supersedes: #N`, `Split-from: #N`, `Folds: #N`, or `Stacked-on: #N`.
Fenced examples do not count. Each predecessor must declare the same `Bead:`
primary item. `Stacked-on` requires its open exact head as the candidate base
and leaves it open. The other trailers authorize retirement: after verifying
the created successor, the command rechecks each predecessor, posts a pointer
to the successor, closes it, and verifies its head and closed state. Branches
are retained. For a split, declare retirement only when the published successor
accounts for the predecessor's remaining work; other split PRs carry that same
work item and lineage. A dry run includes the retirement plan without writes.
Malformed declarations or mismatched item identities refuse before creation.
If retirement fails or races after creation, exit 2 names the existing successor;
inspect and reconcile it rather than repeating creation. GitHub offers no
atomic expected-head close, so a raced close remains unverified.

Overlap file coverage is bounded at 3,200 open PRs and fewer than 3,000 changed
files per PR. Missing metadata, failed reads or bound exhaustion produce an
explicit UNKNOWN warning and a draft, never a claimed disjoint result. Duplicate
creation is checked separately without depending on other PRs' file inventories.

Candidate identity, committed/published source, body primary marker and duplicate
checks still protect concrete write hazards. A changed local/remote candidate
refuses before posting. An existing PR for the candidate branch is excluded from
its own read report; creation refuses a duplicate. `--dry-run` previews the same
body and draft decision without posting. A lost create response or mismatched
resulting head/base remains **indeterminate**: inspect the remote PR before retrying.
GitHub has no atomic expected-head create endpoint, so a branch race after the
last read is detected on the result, not prevented. This command provides the
crew creation path; it does not intercept raw `gh` or other clients. Merge checks
and independent review requirements remain on the merge path.

## Explicit push destination

`st repo push <repo> [agent]` and its deprecated top-level alias refuse an omitted or empty
`--branch` before contacting any remote. Publish a candidate with
`--branch <feature-branch>`; use `--source-branch <feature-branch>` when the selected
worktree is on that topic instead of its canonical agent branch. The source must
match the selected worktree and caller. An explicit path selects the source tree;
it does not bypass the caller-checkout guard. Run the command from that selected
checkout, including when publishing an extra worktree. When changing directories,
use an absolute source path in the repeated push command. Existing authority, pre-push hooks and
non-fast-forward checks still apply to every trusted peer.

`--branch main` explicitly selects a destination; it does not establish independent
review or successful CI. Land reviewed PRs through the normal merge helper rather
than treating source publication as a reviewed merge.

Pushes default to a 600-second per-peer deadline, including local pre-push
checks, so normal validation hooks can finish before publication. Use
`--timeout SECONDS` to select a deadline between 1 and 3600 seconds.
Hooks and publication guards still run.
A timeout leaves publication indeterminate: read back that peer's exact
remote destination SHA before deciding whether any retry is needed. Remaining
peers are not attempted after a timeout, and earlier successful peers stay published.

## Mirror-only remotes

A remote that is advanced only by a mirror protocol, such as a scrubbed public
copy, is declared with `git config remote.<name>.st-push-role mirror`. `st repo
push` never contacts it and reports it as `skipped (mirror)`, even if it is also
marked `st-push-allowed=true`. A mirror never proves publication to the cycle
loss gate, because its history is rewritten. `st-push-role peer` declares a
trusted peer, equivalent to `st-push-allowed=true`. Any other role value refuses
before any remote is contacted, and so does a remote set in which every remote
is a mirror. Advance a mirror only through its own reviewed mirror sync.

## Push freezes and selected peers

`st repo push` keeps its default fan-out to all approved peer remotes. Add
`--remote origin` to publish only that configured peer, or repeat `--remote` for
an explicit subset. Source and destination branch checks, peer authorization,
mirror exclusion, hooks and bounded push deadlines still apply. Selection does
not grant authority to an unapproved upstream.

Before a maintenance freeze, the operator records a reason in Git configuration
for every effective push hostname, on each crew host that can publish:

```bash
git config --global --add st.push-freeze.forge.example 'maintenance window'
```

The key is `st.push-freeze.<host>`. Any configured value, even an empty reason,
means HOLD. The tool reads all scopes/values; a local empty value cannot override
a global freeze. Only the owning operator releases it by removing its values
from the same scopes after the window passes. There is no automatic time expiry
or push-command bypass. A chat announcement alone cannot be detected locally.

Every selected peer's effective push URLs (including multiple pushurls and Git
URL rewrites) are preflighted before any peer is contacted. A frozen host or an
unreadable URL/config refuses the whole set. Mirrors remain uncontacted. The
check repeats before each push; a hold appearing after an earlier publication
stops the remaining writes and reports partial publication. It never rewrites
an earlier remote to undo a push.

Host matching uses the Git URL's hostname, not DNS or SSH alias resolution.
Record all aliases used in push URLs. Hosts that cannot be represented by the
freeze key (for example, a raw IPv6 literal) refuse instead of assuming unfrozen.
This client check does not intercept raw
`git push`, prevent other clients, or cancel a push already in flight. Operator
freeze coordination and server-side write controls remain necessary.

## Squash-merged work and worktree maintenance

Cycle loss checks do not require a merged feature branch to remain on a remote.
Commits count as landed when their exact changed paths, old/new blob IDs and file
modes match a non-merge commit in the bounded trusted-main history, or when they
are reachable from the recorded head of a merged
PR in that same repository. The merge commit must also be reachable on trusted
main. Output names the rule that cleared the work. Unproved follow-up commits
still refuse a cycle; dirty tracked files remain protected.

Merged-PR metadata uses a bounded page and an atomic, repository-local cache in
the common Git directory. A missing record, unavailable forge, malformed response
or truncated history never certifies a landing. Explicit fetch/refresh boundaries
may read the forge; edit-time checks only use cached evidence and local Git.
Mirror remotes cannot supply a publication or landing proof.
Patch IDs and `git cherry` are not loss proofs: they ignore semantic whitespace.
Exact-delta reads cover at most 512 main commits; unknown or malformed evidence
keeps work protected.

At normal safe project-worktree refresh boundaries, including the existing
scheduled tend respawn path, a clean fully landed topic is detached at the
trusted current main. This never forces a checkout or overwrites local changes.
Each pass may prune up to 32 positively landed, unoccupied merged/gone topic
branches; main/master and unknown work are retained. Pruning rechecks occupancy,
compares the expected branch tip before deletion, and retains a recovery ref at
`refs/st/landed-retained/<old-tip>`. There is no new timer or live-agent checkout
sweep. API cache/page and per-pass limits may leave older branches unclassified.

After a merged topic is detached, create or check out a new topic before
committing new work. Publish it with an explicit `--source-branch`. Push refuses
an unreadable or detached source instead of silently selecting an old canonical
branch. Fresh topics at main are not considered merged topics.

Use `git config branch.<topic>.st-keep true` to retain a named recovery or parked
branch. An untracked alias is not pruned merely because it shares a merged PR's
head SHA; the merged PR must name that same topic, or its upstream must be gone.
