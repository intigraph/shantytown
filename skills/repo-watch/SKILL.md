---
name: repo-watch
description: >-
  Run a watch pass over one repository — read its plans, its open items, its docs, its
  code delta and its open forge issues/PRs through five ordered lenses, and mint an item
  for every gap between what the repo promises and what it ships. Read-only against the repository: a watch pass never
  edits, pushes, merges, deploys, or touches an issue or pull request. Owner, remotes and
  norms are resolved from the knowledge graph at run time, never hardcoded. Triggers on
  "watch <repo>", "repo watch", "dream pass", "what has drifted in <repo>", "review this
  repo for gaps", "docs vs code drift", or a scheduled watcher role. Use graph-extract to
  write findings into the graph and quipu to read it.
allowed-tools:
  - Bash
  - Read
  - Grep
---

# repo-watch — what does this repo promise that it does not ship?

A watch pass reads one repository through five lenses, in order, and produces **one watch
report plus an item for every gap it can evidence**. It changes nothing.

The unit of output is a gap: *X promises, Y delivers.* Not an opinion, not a wish, not a
refactor you would enjoy. If you cannot name both halves and cite where each lives, you
have not found a gap and you should not mint one.

## What this skill will not do

**It is read-only against the repository and against the forge.** No commits, no pushes,
no merges, no deploys, no branch or tag creation, no issue or pull-request mutation, no
comment on a pull request, no production action. The only writes a pass makes are item
tracking and reporting, and an append to its own run log.

This is not caution for its own sake. A watcher is trusted precisely because its findings
cost nothing to ignore. The moment a pass can change the thing it is judging, every one of
its reports has to be audited before it can be believed, and the whole mechanism inverts.

## Before you start

1. **Resolve the repo from the graph.** Owner, remotes and ownership state are DATA. Never
   read them from this file, from a directory name, or from memory.
2. **Take a worktree you own.** A shared checkout's index and HEAD belong to the checkout,
   not to your process, so a sibling session's staging reaches into yours.
3. **Fetch before you anchor.** An anchor taken against a stale remote-tracking ref records
   a delta that has already been superseded, and every finding downstream inherits it.
4. **Fetch EVERY remote and compare them.** A repo with two remotes can have one of them far
   behind, and the tracked one is not always the current one. Anchoring on a remote that is
   behind produces a pass that reads a stale tree and reports "no delta" with total
   confidence. Record which remote you anchored on, and whether the others agree.

5. **Anchor on the REMOTE, and verify the old anchor is still reachable from it.**
   Record with `git rev-parse origin/main`, never `HEAD` — HEAD belongs to whoever last
   touched that checkout, and on a shared checkout that is not you. Then verify:

       anchor = repo_watch.verify_anchor(
           repo_watch.Anchor(repo=name, sha=prior_sha), repo_path)   # raises UnreachableAnchor

   It takes an `Anchor`, not a bare sha; a string is refused with a `TypeError`.

   ⚠️ **An UNREACHABLE anchor is worse than a stale one, and it is nearly invisible.** A stale
   anchor is behind but resolvable, so the delta is merely out of date. An unreachable anchor
   makes the delta **uncomputable**, and `code_range` has no range to return — so a
   conscientious pass reports "BOOTSTRAP — no delta" and restates the repo's current state as
   new findings. Measured (internal-ref): shantytown's 2026-08-30 pass anchored on `5a301c7e`,
   a LOCAL unpushed commit on a side branch — present in 1 of 36 clones and **0 remote refs**.
   The next pass would have reported a clean first look at the repo with the highest churn of
   the night, and only a hand check caught it.

   `verify_anchor` now REFUSES that, and `code_range` raises rather than returning `None`, so
   the two cases can never again render the same. A **failed fetch** leaves `reachable=None`,
   not `False` — "could not ask" and "asked, it is gone" have opposite remedies (re-run vs
   re-anchor), so an outage must not read as data loss.

> ⚠️ **MEASURE IN THE TREE YOU ANCHORED ON.** This is the mistake this skill's own first pass
> made, so it is written at the top rather than in a footnote: the anchor was taken from the
> tracked remote, the measurements were run in the working checkout, and the checkout was 73
> commits ahead. Two of the four numbers in the first gap item were wrong — each individually
> plausible, none reproducible from the stated anchor.
>
> A finding is only as good as the tree it was measured in, and a report that names one sha
> while quoting another tree's numbers is *worse* than an unmeasured one: it is falsifiable in
> principle and wrong in practice, so it survives review and fails later.
>
> Use `git show <anchor>:<path>` for single files, or a detached worktree at the anchor for
> anything needing a build or a test run — never the shared checkout, whose HEAD belongs to
> whoever last touched it.

## Step 1 — resolve the repo

```bash
Q() { curl -s --max-time 30 "${GRAPH_URL}/query" -X POST \
        -H 'Content-Type: application/json' -H 'X-Quipu-Client: repo-watch' \
        -d "$(jq -cn --arg q "$1" '{query:$q}')"; }
```

`repo_watch.resolve_query(name, ns)` builds the query. Three things about it are
deliberate, and each cost something to learn:

- **It follows aliases in both directions.** For each entity with an owner,
  use `FILTER EXISTS` to test whether `(owl:sameAs|^owl:sameAs)*` reaches an exact
  `rdfs:label` or `skos:altLabel` match. This keeps each traversal bound to one
  ownership entity; an unbound path joined to a label UNION can scan the whole graph.
  A one-way knot is enough, even when the matching alias has no owner and its label
  was never copied onto the canonical entity. Zero hops retains direct ownership.
  This is a read-only traversal: never assert inverse edges to make resolution
  succeed, and never modify acceptance probes to simulate materialisation.
- **It is `DISTINCT`.** Denormalisation means one name usually matches both the label and
  an altLabel of the same entity, so the un-deduplicated form returns each owner two or
  three times. Nothing is wrong when that happens, but a caller counting rows reads it as
  ambiguity.
- **State and remotes are `OPTIONAL`.** A repo with an owner but no recorded ownership
  state must still resolve; requiring them turns a partly-described repo into an
  unresolvable one, which reads as a broken resolver rather than an incomplete graph.

**If no owner comes back, STOP and say so.** Do not guess, and do not fall back to the
roster in your head. There are two causes and they are indistinguishable from the empty
result: the repo is genuinely unowned, or its owner is recorded only as prose in a
`rdfs:comment`, which SPARQL cannot see. Both are writes for whoever holds the ownership
map. A pass that guesses an owner mints work at the wrong person and looks authoritative
doing it.

## Step 2 — the five lenses, in this order

The order is the contract. Plans establish intent; items say what is already claimed; docs
state what was promised; code says what is true. Reading them in this order means every
later lens can cite an earlier one, and every gap comes out phrased as a comparison rather
than a complaint.

### Lens 1 — plans

Read the design docs and any design-labelled items. You are looking for **status banners
that contradict the repo's own history**: a plan marked "not started" for something that
shipped, a "rejected" decision the code now implements, two plans that assume different
answers to the same question.

### Lens 2 — items

Read the **full corpus** — every item, not the ready pool and not a title search. Both
shortcuts lie here and both lie reassuringly:

- The ready listing **truncates by default**, so an absence read from it is frequently an
  artefact of the limit. Ask for the whole thing, and say what limit you ran under.
- The store's search matches **titles only**. A phrase living in a description or a comment
  comes back as "not found" — in the exact words of a true absence. Grep the exported
  corpus instead.

This lens has prior art: a citation-drift check that compares each item's `updated_at`
against the newest commit citing it by id. A commit newer than the item is positive
evidence the world moved while the item was not listening. **Reuse it rather than
rebuilding it** — that instrument exists because someone fixed a condition, cited the item
by id in the commit subject, and the item went on asserting the unfixed state underneath a
cluster of work built on it.

### Lens 3 — docs

Compare README and book/reference claims against the shipped surface, over the delta since
the last anchor. The productive question is not "are the docs complete" — they never are,
and that finding helps nobody. It is **"where do the docs state something the code has
stopped doing?"** A capability that moved leaves its old description behind, stated with
full confidence, and that is worse than an omission because a reader acts on it.

> ⚠️ **ASK THE PROGRAM, DO NOT GREP THE SOURCE — and check for an existing guard FIRST.**
> Both halves are from a wrong finding this lens produced on its first real pass.
>
> A doc claim about a program's surface must be checked against **what the program builds
> at runtime**, not against a text search for the lines that look like they build it. I
> counted a CLI's commands by grepping its registration calls, got 26, and filed a
> confident gap against a badge that said 29. The badge was right: three commands were not
> literal registrations, so no text search could see them. Building the parser and reading
> its own list of choices answers in one line and cannot miss them.
>
> Note the shape, because it is seductive: I had *already* corrected the naive version of
> that grep once, and the corrected version was still wrong — it traded an overcount of
> four for an undercount of three. **A refined wrong method reads as a careful one.**
>
> And before minting any docs-drift gap: **grep the test suite for the claim.** The existing
> guard here not only asserted the command count, it also encoded a deliberate tolerance for
> the test-count badge — never tolerating an OVERSTATED count, but allowing understatement,
> so that adding a test does not force a README edit. My "gap" was inside that tolerance by
> design. A repository that guards a claim has already decided what correct means for it,
> and that decision is better informed than a fresh reading of the artefact.

### Lens 4 — code

Read the delta since the anchor: `repo_watch.code_range(anchor, head)` — which RAISES
`UnreachableAnchor` if the recorded sha resolves in no clone of the canonical remote (step 5).
Do not catch it into a bootstrap: that is the internal-ref defect. On a bootstrap pass
this is `None` — a first pass has no delta, and manufacturing one restates the entire
repository as new findings. Record the anchor, report the current state from the other
three lenses, and say plainly that it was a bootstrap.

### Lens 5 — the forge sweep (issues and pull requests)

Every OPEN issue and pull request with no tracking item gets one. Use the forge's own
CLI or API — `gh` for public repos, the Forgejo API at `${FORGE_URL}` for internal ones.
`repo_watch.sweep_candidates(items, repo)` turns either forge's JSON into candidate gap
titles; it reads `number`, `title` and `state`, which is the only ground the two shapes
share.

**This extends the CI watcher, it does not duplicate it.** A CI watcher reports *run
state transitions* per workflow — passing→failing, once. This lens reports *open objects
with no item*. Different objects, different lifetimes; if you find yourself reporting a
red run here, you are in the wrong lens.

Two details that are easy to get wrong and silent when you do:

- **A PR is detected by the PRESENCE of a pull-request marker, not its truthiness.**
  `gh` emits `pull_request` as an object that is sometimes `{}`, and `{}` is falsy — a
  truthiness test relabels *some* real PRs as issues, so a sample looks correct.
- **A non-open item is not a gap.** Anything not `open` returns None rather than being
  swept up and deduplicated later.
- **A refusal is not a count.** A forge refuses IN-BAND: Forgejo answers a token without
  `read:issue` with a JSON **object** (`{"message": ...}`) where a listing is an array.
  `len()` of that object is 2 and iterating it is 0 — both are numbers read off an error
  (internal-ref.1). Pass the parsed JSON to `sweep_candidates` as-is and never count it
  yourself: a non-list raises `ForgeListingError`, which you report as **CANNOT TELL**
  for that repo, with the forge's message, never as a number of open issues.

## Step 3 — dedupe against the corpus, THEN cap

```python
r = repo_watch.triage(candidates, corpus, cap=7)
#  r.mint       -> create these, labelled repo_watch.mint_labels(repo)
#  r.update     -> an OPEN watch item already covers this; UPDATE it, do not re-mint
#  r.duplicate  -> an existing item covers it; do nothing
#  r.ambiguous  -> report candidate AND possible item id; human adjudication required
#  r.held       -> over the cap. Report them: r.withheld_line(7)
```

> ⛔ **NEVER BUILD `corpus` FROM A TITLE SEARCH.** The store's search matches TITLES ONLY
> and reports that blindness in the exact words of a true absence. Every directive and
> finding on this fleet is prose in a DESCRIPTION or a COMMENT — so a title-only dedupe is
> structurally blind to precisely what it is checking for, and it would report "no
> duplicates" most confidently for the subjects that have been discussed most.
>
> **This is the single most likely way this lens ships broken while appearing to work.**
> Export the full JSONL corpus and pass that.

**A re-found gap UPDATES its existing watch item.** Minting a second item for a gap that
is already open is how a watcher turns a board into noise across passes rather than within
one. Two guards on that, both deliberate: a **closed** watch item is a duplicate, not an
update — the gap was dealt with, and a genuine regression deserves a new item with a new
argument; and an item a **human** wrote is never updated by the watcher, because a watcher
editing someone else's item is how its reports stop being trustworthy.

**The cap must SAY what it withheld** — `r.withheld_line(cap)` names the subjects, not just
a count. A count alone cannot be checked against the next pass, and a cap that silently
drops findings is a filter nobody can audit.

**Prove the dedupe FIRES.** `triage(..., dedupe=False)` exists only as the positive control:
a dedupe that has never been observed minting the duplicate when disabled is
indistinguishable from one that silently never matches anything. Never run a real pass with
it off.

**Dedupe runs before the cap, and the order is load-bearing.** Reversed, duplicates consume
the budget and push real findings into the held pile — the pass then reports that it hit the
cap while minting nothing new, which is the worst of both outcomes.

Closed items count as duplicates. A gap found and fixed last week must not be re-minted this
week; if it has genuinely regressed, that is a different item with a different argument and
it deserves to be written as one.

Nothing is discarded. Everything over the cap comes back as `held` so the report can name
what it is holding.

## Step 4 — anchor the pass

The anchor is a **signed shuttle advance**, so that "when did we last look, and who looked"
is a fact in the record rather than a claim in prose.

```bash
shuttle start repo-watch "$(python3 -c 'import repo_watch,sys; ...')" --agent "$OWNER"
shuttle advance "$RUN" --step anchor  --agent "$OWNER"   # pending  -> anchored
shuttle advance "$RUN" --step observe --agent "$OWNER"   # anchored -> observed
# ... the five lenses, the mint, the report item ...
shuttle advance "$RUN" --step report  --agent "$OWNER"   # observed -> reported (terminal)
shuttle export
```

`observed` and `reported` are STATE names; the STEPS are `anchor`, `observe`, `report`.
Passing a state name as `--step` is refused with the legal steps listed. Verify the run with
`shuttle verify "$RUN"`: it reads the exported transitions back from the window graph and
checks each signature.

> ⚠️ **A shuttle `/knot` lands in a WINDOW graph, not the root graph.** An anchor read back
> in default scope returns ZERO rows — which looks exactly like the advance never landed,
> and the natural recovery is to re-run it. **Read the window scope explicitly**, and verify
> the anchor by reading back the signed step, never from the run's exit code.

## Step 5 — the report

One watch report item per pass. It must carry, because a reader two weeks from now cannot
reconstruct any of it:

- **the anchor** — the sha observed after fetch, and the run id;
- **each lens, named, with what it found or that it found nothing.** A lens that found
  nothing is a result and belongs in the report. A lens silently omitted is
  indistinguishable from a lens that was never run;
- **the mint ledger** — minted, deduped (with the item each candidate matched), held by cap;
- **the safety line** — that nothing in the repository or on the forge was mutated;
- **evidence for every stated cause**, inline: the command and its output, or the word
  INFERRED.

Then tell the repo's owner. A report nobody is pointed at is a report nobody reads.

## Failure modes this skill is built around

| what you will see | what it actually means |
|---|---|
| resolver returns no owner | genuinely unowned, **or** owner recorded only as prose — STOP either way |
| resolver returns the same owner 3× | denormalised aliases; use `DISTINCT`, it is not ambiguity |
| anchor read returns 0 rows | you read root scope; the advance is in the **window** graph |
| item search finds nothing | search matches **titles only** — grep the corpus |
| ready pool "does not contain it" | the pool **truncated**; state the limit or do not claim the absence |
| a lens found nothing | a result — report it, do not omit it |
| one remote far behind the other | anchor on the wrong one and every lens reads a stale tree |
| numbers that do not reproduce | you measured in the checkout, not at the anchor |

Description-only forge references whose same-repository title names another number
are ambiguous, even when the item is closed. Report each candidate and possible
covering item; do not silently suppress it or mint it as definitely untracked.
An exact tracker, including a closed tracker, still wins. Always pass `repo=`
for forge sweep candidates; omitting it disables forge-identity matching.

### Resolver regression checks

Run the offline suite from this directory with `python -m unittest`. To also execute
the generated SPARQL against one-way aliases with no inference, run
`uv run --with rdflib python -m unittest`. RDFLib is a test-only dependency;
the resolver remains standard-library-only. Graph cases cover both edge directions,
mixed-direction chains, cycles, missing owners and conflicting owners.
