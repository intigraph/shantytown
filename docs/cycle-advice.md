# Cycle advice

`st agent advise <agent>` reports keep-or-cycle advice from context depth,
work overlap and cache evidence. Normal `st go` dispatches carry the same notice
in the delivered work and print it for the sender. Advice does not bypass pane,
checkpoint, ownership, capacity or governor gates.

## Automatic handoff evidence

Dispatch compares the already-loaded item's explicit repository labels,
relative source paths and named scope labels with the previous verified
handoff. It performs no extra tracker read and calls no model.

- The same item or shared explicit files gives strong overlap.
- A shared repository, named source package or scope gives partial overlap.
- Different explicit repositories gives low overlap.
- Missing prior facts, missing scope, or merely different files stays UNKNOWN.

These scores measure metadata overlap, not calibrated semantic probabilities.
The notice names its basis. Generic title words and missing facts do not establish
unrelatedness. The first handoff starts with UNKNOWN and seeds facts for later
handoffs. A local work-facts file and signal are recorded only after a verified
send and assignment readback. Failed or dry-run dispatches do not record them.
Persistence failures are reported separately from the successful dispatch.

Signals for different agents use a serialized update, so one handoff cannot erase
another. A completed cycle clears only its own signal. Explicit, fresh caller
judgements for the next item override automatic overlap, including a judgement
posted between preview and recording.

## Cache evidence

Claude usage records supply observed five-minute or one-hour cache-write TTLs.
A fully cached turn can use an earlier write from the same model. A model change
cannot borrow the old model's write TTL. This handles recorded plan/overage
changes through actual usage, without guessing account entitlement.

Codex `event_msg` / `token_count` records supply the latest request time and
cached/write counters. The preceding `turn_context` supplies its model when
available; otherwise the configured card model is labelled as such. Retention
is an **assumed model-policy window** when no explicit TTL was recorded. The
notice and JSON identify that assumption. An unsupported model or unreadable
request time remains UNKNOWN. Scans are bounded by records and bytes.

The [official OpenAI cache guide](https://developers.openai.com/api/docs/guides/prompt-caching)
distinguishes minimum cache lifetime from eviction. Its API defaults do not prove
Codex subscription retention. Elapsed policy windows are advisory estimates;
`cache_lapsed` does not establish that a remote cache entry was evicted.

## Explicit caller interface

```sh
st agent advise <agent> --related 0.85 --by reviewer --next ITEM
st agent advise <agent> --decision cycle --by reviewer --reason 'different work'
st agent advise <agent> --json
```

`--json` includes the full cache evidence and provenance, the signal, advice,
`ask`, and a bounded `brief`. A checkpoint supplied with `--checkpoint-file`
shares that brief fairly with the next task's title and notes. `--brief-chars`
can request more up to `max_brief_chars`; no conversation is included in the brief.
`--next-need-k` estimates fresh context needed by the next item.

The `ask` flag is false at hard context limits or when depth is unreadable,
and when measured CLI evidence already prefers replacement. A caller with
`ask: false` does not call a judge. Checkpoint briefs remain bounded.

## Decision rules

| Situation | Advice |
| --- | --- |
| Hard cycle line or `always_cycle_above_k` reached | Cycle; no signal can extend the ceiling |
| Missing, expired, wrong-item or UNKNOWN judgement | Default; existing depth policy applies |
| Depth plus predicted next need reaches the cycle line | Cycle at the boundary |
| Explicit decision | That decision, below the hard ceilings |
| Strong overlap | Keep |
| Low overlap | Cycle |
| Partial overlap | Compare configured keep/rebuild cost estimates |

Unknown cache timing is priced warm, so missing data alone does not cause a
cycle. Strong overlap can preserve reasoning below the hard ceiling even when
an assumed cache window elapsed. An explicit cycle request still requests a cycle.

## Picking up an installed Claude Code update

`st agent advise --json` includes `running_version`, `installed_version`, and
`runtime_session_id`. Advice names both versions and marks process replacement
with `restart_required`. Missing or malformed versions, a different session, or absent launch evidence
remain UNKNOWN. Equal or older installed binaries give no update preference. Stable numeric versions are compared numerically.

The running version is read from at most the last 256 KiB of native transcript
metadata. Tend uses the exact session last recorded in the local stats store,
and its version record must be newer than the current launch stamp. No newest-file
search or model-name inference is used. A missing stamp/transcript or a session
that the stats reader can no longer bind stays UNKNOWN. A Stop hook has the live
session payload directly and gives one reminder per session/version pair.

The installed version is a local `claude --version` probe with a two-second
limit, cached for at most five minutes and invalidated by executable identity
changes. It does not check the network or run an updater. Current Codex launchers
can select a role-specific standalone binary; this feature does not borrow a
PATH Codex version for that process. Claude Code is the supported measured path.

Tend can prompt even a shallow session, but only when its pane is positively
idle, shell-free and st-wired. It checks the pane again after version lookup,
logs both versions, and deduplicates by session/version pair. Busy, queued,
waiting, auth-limited, foreign, shell-unknown and unreadable panes are not update
candidates. An accepted or unreadable cycle-request ledger prevents competing
prompts. Failed delivery remains retryable. Manual keep advice is preserved;
context hard limits still win.

At a safe handoff, checkpoint first and request replacement explicitly:

```sh
st agent cycle --self --no-in-place --checkpoint-file notes.md \
  --checkpoint-bead <item> --quipu-node <existing-node>
```

An in-place context clear keeps the old process. `--no-in-place` is retained in
the accepted request and uses the existing checkpoint, graph, ownership, idle,
background-work and loss guards. Update advice itself never creates a request,
stops a process, rewrites an accepted request, or installs a binary. After normal
relaunch, verify the new session's native version matches the installed release.
Source tests and an accepted request alone do not prove that result.

## The arithmetic

In thousands of base-input-equivalent tokens, D = depth, F = `fresh_floor_k`,
N = `expected_turns`, r = read multiplier, w = write multiplier for the
session's TTL:

- keep = (w if the cache lapsed else r)·D + r·D·(N−1)
- cycle = w·(F+R) + r·(F+R)·(N−1), with R = related · `rebuild_fraction` · (D−F)

The multipliers default to Anthropic's list prices (read 0.1×, write 1.25× for
5m and 2× for 1h). On a subscription seat the currency is the governor's usage
window, which st cannot see into, so every number is configurable.


## Configuration

```toml
[cycle_advice]
always_cycle_above_k = 350
brief_chars = 1500
max_brief_chars = 6000
keep_at = 0.8
cycle_below = 0.3
signal_max_age_minutes = 120
cache_ttl_seconds = 300 # compatibility fallback for legacy cache objects
read_multiplier = 0.1
write_multiplier_5m = 1.25
write_multiplier_1h = 2.0
fresh_floor_k = 40
rebuild_fraction = 0.3
expected_turns = 10

[cycle_advice.model_cache_ttl_seconds]
"gpt-6*" = 1800
"gpt-5.6*" = 1800
"gpt-5.5*" = 1800
"gpt-5*" = 300
"claude-*" = 300
```

A configured table replaces the default model table. Values must be positive
integer seconds. More specific patterns win independently of TOML key order.
An empty table disables these estimates. Observed transcript TTLs always win;
unknown models do not inherit the compatibility fallback. Multipliers remain
operator-selected cost assumptions, not measured subscription charges.
