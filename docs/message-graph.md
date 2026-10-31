# Messages in their own graph (design)

**Status:** DESIGN, not built. Tracking item: aegis-snq. Nothing in this page is
installed, and no vocabulary named here is admitted yet. Every term marked
*proposed* needs the shape admission step in [Vocabulary](#vocabulary-proposed-not-admitted)
before any code writes it.

## Problem

`st inbox -d` stores each durable message as a seeds work item: title
`inbox: [from X] …`, label `inbox`, priority 2, type task, in the same project
graph as real work. Alert escalations take the same path
(`inbox: [from alerting] ESCALATION…`).

Measured 2026-10-31 on the live board: about 2,700 of these items were open.
They are kept off plates by one title predicate (`inbox.is_message`, and its
SPARQL twin `seeds_plate.MESSAGE_PATTERN`). Everything else sees them: `sd list`,
board counts, search, ready counts, deferral and triage readers. About a dozen
readers each repeat the exclusion, and several of them use the label instead of
the title, so they can disagree. Nothing expires a message; the only closer is
"read it", so an agent that is offline for a week returns to hundreds of
pointers.

The direction (Stiwi, 2026-10-31): messages belong in a different graph from
work items and from ROOT, with their own lifecycle.

## Decisions

| # | Decision | Rejected alternative, and why |
|---|----------|-------------------------------|
| D1 | Messages are their own type, not seeds. | A label or seed type: still a seed, so every board reader still has to exclude it. |
| D2 | They live in **time-windowed message graphs**, one per ISO week: `<project IRI>/messages/<YYYY>-W<ww>`. Never ROOT and never the project graph. | The seeds ephemeral sibling `#seeds-ephemeral`: seeds unions it into every snapshot read, which is the opposite of isolation. One unbounded graph: cannot be archived by Quipu's whole-graph freeze. |
| D3 | Each window carries the Quipu label `dataKind = operational`. Archive is Quipu **deep freeze** of a whole window. | Deleting old messages: destroys delivery evidence. A home-made archive export: duplicates freeze, which already keeps the graph queryable by name. |
| D4 | Delivery, read and ack are three separate, append-only facts with timestamps. Reading never acks and never closes. | Today's "read = close": a count or a listing cannot tell "seen" from "handled", and a startup batch that lands in a dead pane loses the message. |
| D5 | Messages are written and read through a **seeds verb family** (`sd msg …`), not by `st` talking HTTP to Quipu. | `st` writing Quipu directly: a second signing and credential path in `st`, beside the board's own. |
| D6 | A message never carries work. A message that asks for work **refers to a seed** that already exists. Work-graph data never refers to a message. | Messages that become work by being on a plate: the defect `is_message` exists to prevent. |
| D7 | Alerts are messages of `kind = alert`, with one open message per (recipient, alert fingerprint). A re-fire raises a count. | A new message per re-fire: today's escalation flood (see aegis-l7j). Routing alerts only to the alert router: crew then lose the durable "someone told me" record. |

## Graph layout

```
<project IRI>                         work items (unchanged)
<project IRI>#seeds-ephemeral         ephemeral seeds (unchanged)
<project IRI>/messages/2026-W44       messages delivered in ISO week 44   dataKind=operational
<project IRI>/messages/2026-W43       …                                    dataKind=operational
<project IRI>/messages/2026-W40       frozen window                       dataKind=archive
```

- A message is written to the window of its **delivery** time and never moves.
  Its later read, ack, expiry and escalation facts are written to the same window.
- Live readers address windows **by name** (`GRAPH <…/messages/2026-W44>`), from
  the window list the registry returns (`GET /graphs`). A window that is not
  registered is an error, never an empty answer.
- The window prefix is not under `#seeds-…`, so no seeds snapshot, board read,
  pendant, export or `sd sync` includes it. That is the isolation guarantee, and
  it is structural rather than a filter.
- Default search (`quipu_search`) excludes message windows through
  `[quipu.search] exclude_graphs` (a deployment setting). `st inbox --search`
  passes an explicit graph scope.

## Vocabulary (proposed, not admitted)

Prefer schema.org terms that seeds already uses, so that only the shape is new:

| Field | Proposed term | Cardinality |
|-------|---------------|-------------|
| type | `schema:Message` | 1 |
| id | `schema:identifier` (a seeds-style id, `<prefix>-m…`) | 1 |
| from | `schema:sender` (agent IRI; absent means UNKNOWN, never "system") | 0..1 |
| to | `schema:recipient` (agent IRI) | 1 |
| delivered | `schema:dateSent` | 1 |
| body | `schema:text` | 1 |
| refers to | `schema:about` (seed IRI) | 0..n |
| kind | *proposed* `shanty:messageKind`: `note`, `request`, `alert`, `receipt`, `escalation` | 1 |
| delivery key | *proposed* `shanty:deliveryKey` (today's `urn:shantytown:inbox:<sha>`) | 0..1, unique per window set |
| read | `schema:dateRead` | 0..1 |
| acked | *proposed* `shanty:dateAcked`, `shanty:ackedBy` | 0..1 |
| expired | *proposed* `shanty:dateExpired` | 0..1 |
| escalated | *proposed* `shanty:escalatedTo`, `shanty:dateEscalated` | 0..1 |
| alert | *proposed* `shanty:alertFingerprint`, `shanty:fireCount` | kind=alert only |
| legacy | *proposed* `shanty:legacySeed` (the migrated seed id) | 0..1 |

Admission: confirm that `schema:Message` and each term above are in the server's
loaded vocabulary. Submit the missing ones, with a SHACL shape, as a Quipu shape
proposal. Land the accepted shape in the seeds shapes file so it survives a
redeploy. Until that read-back succeeds, nothing writes a message node.

## Lifecycle

```
delivered ──read──▶ read ──ack──▶ acked
    │                 │
    └──── 24 h unread: one escalation message to the recipient's lead
    └──── 7 d: expired (unless acked)            ─▶ window frozen (archive)
```

- **delivered.** `deliver()` writes the node and reads it back before it reports
  success. This is today's survival guarantee, unchanged.
- **read.** `st inbox --read` and the startup batch set `dateRead` only for what
  was actually shown. The startup batch sets it only after the
  `ST-STARTUP-INBOX-COMPLETE` marker is verified on screen, as it does today; a
  dead pane leaves the message unread.
- **ack.** `st inbox --ack <id>` (or `--ack-all-read`). A `note` or `receipt`
  needs no ack. A `request` or `alert` counts as outstanding until it is acked.
- **escalation.** A tend pass finds `request` and `alert` messages unread for
  24 h, sends **one** `escalation` message to the recipient's lead (delivery key
  `escalate:<message id>`, so it is sent once at most), and records
  `escalatedTo`. It never escalates an escalation.
- **expiry.** After 7 days any message that is not acked gets `dateExpired`.
  Expired is a terminal state. It is not a delivery failure, and it is never
  silently counted as acked.
- **archive.** A window is frozen once its week ended more than 7 days ago and
  every message in it is acked or expired. A window that fails that test is
  reported, not frozen. Thawing restores it exactly.

A count of what needs attention is the number of `request`/`alert` messages
neither acked nor expired. "Unread" stays a separate count.

## Alerts

- The escalation poller keeps calling `st inbox -d`, with `--kind alert
  --fingerprint <fp>`.
- When an open (not acked, not expired) alert with the same recipient and
  fingerprint exists, `deliver` adds to `fireCount` and records the new time on
  that message instead of creating one.
- Acking an alert does not clear the fault. Clearing stays with the alert
  router's own ack (`alert-ack.sh`).

## Seed references

- `deliver(..., about=[seed ids])` checks that each seed exists (one exact-ID
  read) before writing. An unknown ID refuses the send.
- Every edge points from a message to a seed, never back. The seeds validator
  already refuses shared-to-ephemeral edges; extend that refusal to any
  work-graph edge into a message window (a new check in phase 2).
- `st inbox` shows referenced seeds as IDs. Opening the work is
  `st work item show`, not a message action.

## Code seams (shantytown)

Mapped at 7420239:

| Seam | Change |
|------|--------|
| `inbox.TrackerInbox` | New `MessageGraphInbox` implementing the same `Inbox` protocol (`deliver`, `deliver_once`, `unread`, `unread_count`, `unread_view`, `unread_selected`, `find_delivery`) plus `ack`. `mark_read` sets `dateRead` only. |
| `sd.SdTracker.create_inbox_message`, `inbox_items`, `inbox_count`, `inbox_page`, `inbox_receipts` | Call `sd msg create/list/count/show` instead of `sd create`/`sd list`. |
| `seeds_inbox.read`, `seeds_inbox_window.*` | Read message windows by name; stop unioning `#seeds-ephemeral`. |
| `cli._tracker.notify`, `producer_capacity.main.notify` | These write `inbox:` seeds with a plain `create`, bypassing `deliver`. Convert them to `deliver` **before** cutover, or they keep writing to the work graph. |
| `inbox_bridge.main` | Hard-wired to the br tracker; take the selected inbox instead. |
| `cli._inbox` | Selects `MessageGraphInbox` when `[inbox] store = "message-graph"`. |
| Exclusion readers (`is_message`, `MESSAGE_PATTERN`, `plate_capacity`, `overdue`, `due_brief`, `ranking_check`, `board_triage`, `deferrals`, `feed_check`, `priority_advisory`, `busy_wait`) | Unchanged until the legacy drain reaches zero; then removed in one change. `overdue.verify_inbox_receipt` requires the `inbox` label and moves to `find_delivery`. `seeds_plate.ready_count` counts messages on purpose; that inclusion is dropped. |

Callers that live outside this repository and read or close inbox seeds
directly in the work store (an escalation reconciler, a 24 h pointer-TTL
closer, a cron inbox reader) must move to `st inbox` verbs in the same release.
The pointer-TTL closer is then retired; expiry replaces it.

## Rollout

Each phase has its own item, its own before/after probe and its own rollback.

1. **Vocabulary.** Shape proposal, admission, and read-back of the loaded
   vocabulary. Rollback: withdraw the proposal; nothing is written.
2. **Seeds verbs.** `sd msg create|list|count|show|read|ack|expire` on windowed
   graphs, signed the same way as board writes. Window registration and the
   `operational` label happen on first write. Isolation test: every board read
   (`list`, `ready`, `count`, `show`, plate SPARQL, pendant, export) gives
   identical bytes before and after 1,000 messages are written.
3. **Dual read, new writes.** `[inbox] store = "message-graph"`. New messages go
   to windows. `unread` is legacy unread seeds ∪ window unread, with legacy IDs
   shown as they are today. Acking a legacy ID closes the seed, which is today's
   behaviour. Rollback: flip the setting back; window messages stay readable
   through `sd msg list`.
4. **Legacy migration** (below).
5. **Drop dual read** and the exclusion predicates once a full-board count of
   `inbox:`/`mail:` seeds that are not closed is zero.
6. **Expiry, escalation and freeze** run as a scheduled tend step, after the
   freeze command has been rehearsed on a copy.

## Legacy migration

Open legacy seeds become messages. Closed ones stay as closed seeds: they are
already off every plate, and moving tens of thousands of historical rows buys
nothing. The cost of moving them can be measured and decided separately.

1. **Export first.** Export every open `inbox:`/`mail:` seed (id, title,
   assignee, description, labels, created, status, version) as N-Triples, with
   a sha256 of the canonical form and a count for each recipient. The export is
   the rollback.
2. **Dry run.** Map each seed to a message: `sender` parsed from `[from X]` or
   the `from X` description (absent if neither parses), `recipient` = assignee,
   `dateSent` = created, `text` = body, `kind` = `alert` for `ESCALATION[`
   titles and `note` otherwise, `legacySeed` = seed id. Report how many map,
   per recipient and per kind, plus every seed that does not parse. Write nothing.
3. **Write.** Write the messages into the windows of their creation weeks and
   read every one back. Close each seed with reason `migrated to <message id>`
   only after its message reads back.
4. **Reader proof.** Each recipient's unread count before migration equals the
   count after (legacy plus windows). Plates, `sd ready` and board counts are
   unchanged except for the closed legacy rows. A sample of 50 IDs round-trips
   both ways.
5. **Inverse.** Reopen each migrated seed at its exported version, retract the
   messages carrying `legacySeed`, and check the per-recipient counts against
   the export manifest. The inverse is rehearsed on a store copy before the live
   run.

## Out of scope

- The message size cap. Moving the body from the title to `schema:text` removes
  the title limit, but that cap belongs to a separate item. It is not changed here.
- Who may message whom. Today's sender identity rules are unchanged.
- Delivery into panes, and its verification. Unchanged.

## Open questions (with recommendation)

1. **Window size.** Weekly (recommended: it matches the 7-day expiry, and at
   most three windows are live) or monthly, as shuttle uses (fewer graphs, but a
   window freezes up to 5 weeks after its first message).
2. **Who owns `sd msg`.** Recommended: seeds, because it owns the signed write
   path and the shapes file. The alternative is a shantytown-owned writer that
   holds a second credential.
3. **Should `note` messages expire faster?** Recommended: no. One TTL is easier
   to reason about, and the cost is a few days of storage.
