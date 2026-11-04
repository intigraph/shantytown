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
