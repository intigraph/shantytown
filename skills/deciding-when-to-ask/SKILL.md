---
name: deciding-when-to-ask
description: >
  Decide whether to handle a decision yourself or bubble it up to a human, so a
  coordinator stays heads-down and only surfaces genuine human-in-the-loop
  calls. Use this skill when asked "should I ask the human about this?", "handle
  it or escalate?", "is this safe to do autonomously?", when you are a
  coordinator/administrator agent about to interrupt an operator, or whenever you
  catch yourself asking permission for routine reversible work. Gates on
  reversibility / blast radius (Bezos's one-way vs two-way door), not on how
  confident you feel; routes human contact by type (Approval / Input /
  Escalation); batches like-kind approvals; tiers by burn rate the way SRE
  alerting does. Portable: pure judgment discipline — no service, no framework.
---

# Deciding When to Ask

You are asking the human too much. The fix is not "ask less" — under-asking is
its own failure (a silent wrong guess is worse than an interruption). The fix is
a **rule** for which decisions cross the line, applied per decision, so the calls
you make yourself and the ones you surface are both defensible.

**The one reframe that changes everything:** gate on **reversibility and blast
radius**, not on how confident you feel. Confidence is a *secondary* signal that
sits on top of the gate — two separate research claims that tried to route
escalation on a confidence threshold *alone* were refuted. A cheap, reversible
action you are only 60% sure about: **do it and watch.** An irreversible,
high-blast-radius action you are 95% sure about: **still escalate.** The axis is
the door, not the odds.

> Two-way door (reversible, low undo cost) → **handle it yourself, fast, at ~70%
> of the information you'd ideally want.** One-way door (irreversible, high undo
> cost) → **pause and escalate.** Applying slow one-way-door scrutiny to a
> two-way-door decision is itself a failure mode — bureaucratic over-escalation.

**Stack tools this reaches for**

This skill is judgment, not a program — it needs nothing installed. What it
reaches for is where the *output* of a decision goes:

| Present | This skill uses it for | Absent — what happens |
|---|---|---|
| a tracker (`bd`, `gh`, files) | slow-burn escalations become a **ticket**, not an interrupt; every autonomous call worth an audit trail gets recorded | you hold it in your head; the human can't sample your auto-approvals later |
| **[notify](../notify/SKILL.md)** | fast-burn escalations **page** a human on the transport they actually watch | you print the escalation and must say out loud it was not delivered |
| **[dispatch-work](../dispatch-work/SKILL.md)** (`st`) | the two-way-door work you *didn't* escalate still has to get done — hand it to a worker | you do the reversible work inline yourself |
| **[quipu](../quipu/SKILL.md)** graph | "has this class of action been pre-approved / bitten us before" before you decide it fresh | you re-adjudicate a decision the fleet already settled |

> **On confidence.** If your runtime exposes a calibrated uncertainty signal,
> use it as the *tiebreaker inside* a tier — never as the tier itself. Frontier
> agents are systematically miscalibrated (verbal "90% sure" is often far
> lower), so a confidence number is an input to the reversible/irreversible
> call, not a replacement for it.

## The per-decision checklist

Run this on any decision you're tempted to escalate. It is five questions and it
terminates fast:

1. **Is it reversible?** Can you walk back through the door — undo, roll back,
   restore — at low cost? If **no**, → escalate (one-way door). If **yes**, keep
   going.
2. **What's the blast radius?** Read-only / dev / staging / one item you own →
   small. Production, shared state, other agents' work, anything external →
   large. Large blast radius on an irreversible action → escalate even if you're
   confident.
3. **Is it on the escalate-list below regardless?** Delete/drop/revoke, external
   comms, spending money, access or security posture, a production deploy, or a
   resource only the human can create (a credential, a paid plan, a physical
   thing). If yes → escalate, full stop.
4. **Can I batch it?** If it's one of many *like-kind* low-risk actions, don't
   ask N times — hold them and ask **once** (see Batching). Do not batch
   heterogeneous or high-blast-radius actions under one approval.
5. **Which route?** If you are escalating, it is exactly one of three types —
   Approval, Input, or Escalation (see Routing). Pick the right route; a generic
   "hey, question" is the thing you're trying to stop doing.

If 1–3 all clear, you have a two-way door: **act at ~70% info, then verify the
result.** Record it if it's worth an audit trail. Do not ask.

## Handle it yourself vs escalate

| Handle it yourself (two-way door) | Escalate (one-way door) |
|---|---|
| Read-only ops: queries, lookups, status, analysis | **Delete / drop / revoke** — anything destructive without an undo |
| Dev / staging / scratch changes | Production deploy or migration |
| Low-risk change inside an **established pattern** | A change that sets a **new** pattern or precedent |
| Retrying, re-dispatching, unblocking a stuck worker | **External comms** — anything a person outside the fleet sees |
| Reassigning work between agents you coordinate | **Spending money** / anything above a cost threshold |
| Batched like-kind edits (e.g. relabel 40 items) | **Access / security posture** — keys, perms, exposure |
| Picking the next ready item off the queue | A resource **only the human can create** (paid plan, secret, hardware) |
| Anything you can fully roll back in one step | Anything whose reversal needs *someone else's* cooperation |

The rows are illustrative, not exhaustive — but the sorting rule is exact:
**reversible + bounded blast radius → your call; irreversible or wide blast →
their call.** When a case is genuinely on the line, treat "can I cleanly undo
this in the next five minutes, alone?" as the deciding question.

## Route by type — not one generic "ask"

When you *do* contact the human, it is one of three distinct things, and each has
a different shape. Naming the type is half of not being annoying:

| Type | You are saying | Shape |
|---|---|---|
| **Approval** | "I know exactly what I want to do; I need a yes/no." | A single decision with a default and a deadline. Binary. |
| **Input** | "I'm blocked on a fact only you have." | A specific question — the missing value, not "what should I do?" |
| **Escalation** | "I hit something I cannot recover from." | An unrecoverable blocker + what you already tried. |

Most over-asking is **Approval and Input dressed up as Escalation** — vague,
open-ended, "what do you think?" Convert them: an Approval names the action and
asks yes/no; an Input names the one missing fact. If you can't reduce your
question to one of these three, you probably haven't finished thinking, and the
human shouldn't pay for that.

### Batch like-kind approvals into one decision

An agent that generates 100 actions overnight needs **one batch review, not 100
popups.** Hold like-kind, low-per-item-risk approvals and surface them together:
"I'm about to relabel these 40 stale items → [list] — approve all?" is one
interruption; forty prompts is alert fatigue you manufactured.

**The batching guard:** only batch **homogeneous, low-per-item-risk** actions.
Never fold heterogeneous or high-blast-radius operations under a single approval
— "delete these 100 things" is not one two-way door because *one* of them might
be the one-way door you didn't look at.

## Volume discipline, borrowed from SRE

Escalation is alerting. SRE already solved "when does a signal deserve a human,"
and the rules port directly:

- **Escalate on burn, not on every breach.** Alert only on events consuming a
  large fraction of the budget — a naive threshold can fire 144 times a day while
  everything is fine. Ask yourself: does *this* decision actually move the needle,
  or am I narrating?
- **Tier by burn rate.** Fast, large burn → **page** (interrupt now, via
  [notify](../notify/SKILL.md)). Slow, small burn → **ticket** (file it, let
  them get to it). Most of what you're tempted to ask is a ticket. Google's own
  cut: fast budget burn pages; slow burn opens a ticket.
- **Measure it so it's tunable, not a gut call.** Score your escalations with
  **precision** (of the things you escalated, how many were genuinely worth it)
  and **recall** (of the things that genuinely needed a human, how many you
  caught). Over-escalation is low precision; under-escalation is low recall. An
  agent-specific version (**Ask-F1** = harmonic mean of question precision and
  blocker recall) is built so you *cannot* score well by spamming: 80% recall via
  50 questions at 8% precision scores ~14.5%. Log every escalation and its
  outcome; review the two rates; move the line.

## Why this is the binding constraint

Knowing *when* to ask is not a nicety — it is the skill that's actually missing.
Frontier agents solve **75–89%** of fully-specified tasks but only **4–24%** when
they must decide for themselves when to ask a human, even with an `ask_human()`
tool available. Raw capability isn't the gap; **judgment about when to escalate
is.** That gap shows up as three concrete patterns — watch for all three in
yourself:

1. **Overconfident wrong belief, no gap detection** — you never noticed you were
   unsure. (Antidote: run the checklist even when you feel certain.)
2. **Detected uncertainty, errored anyway** — you *knew* it was shaky and acted
   without asking. (Antidote: on a one-way door, high uncertainty is a hard
   stop.)
3. **Broad, imprecise escalation** — you asked, but vaguely, and didn't
   self-correct. (Antidote: route by type; make it Approval or Input.)

## Failure modes — aim for the interior optimum

There is no "always ask" and no "never ask." Team accuracy follows an inverted-U:
push the ask-threshold too high or too low and both get worse. The four ways it
goes wrong:

- **Over-escalation → alert fatigue.** Ask too often and the human tunes you out;
  your *real* escalation then lands in a muted channel. Disuse.
- **Under-escalation → silent wrong guess.** Ask too rarely and you commit an
  irreversible mistake nobody got to veto. This is the expensive one.
- **Automation complacency (their side).** When your escalation volume drops, the
  human stops scrutinizing what they do see, and rubber-stamps. Keep them
  meaningfully engaged by sampling — surface a fraction of auto-approved
  reversible actions for audit, so oversight stays real.
- **Bureaucratic over-scrutiny.** Applying one-way-door deliberation to two-way
  doors. Reversible work should be *fast*; slowing it to be safe wastes the one
  thing the reversibility was buying you.

Calibrate the line against **your own** history, not a generic benchmark. The
specific "act above 0.70 confidence" numbers that float around come from a
synthetic toy simulation — treat the inverted-U *shape* as real and the specific
operating point as something you must find on your own fleet's data.

## Configure (config, not constants)

Nothing here is required, but if you want the tiers to be tunable rather than
baked into prose, read them from the environment:

```bash
export ASK_COST_THRESHOLD=0            # spend above this always escalates (your currency)
export ASK_BATCH_WINDOW_SEC=0          # hold like-kind approvals this long before surfacing
export ASK_BATCH_MAX=25                # cap on a single batched approval
export ASK_AUDIT_SAMPLE_RATE=0.05      # fraction of auto-approved actions to surface for audit
```

A threshold that lives in an env var is one you can move when your precision and
recall tell you to. A threshold baked into a sentence is one you'll argue with.

## Prove the line can move

A gate you never tune is a gate you can't trust. Once a week (or once per N
decisions), pull your escalation log and compute the two rates by hand:

```text
precision = (escalations the human said "yes, glad you asked") / (total escalations)
recall    = (escalations that mattered)                        / (things that actually needed a human)
```

If precision is high and recall is low, you're under-asking — loosen the gate
(more things cross to escalate). If precision is low, you're over-asking — tighten
it (more things you handle yourself). If you have never once moved the line, you
have not calibrated it; you've only guessed and stopped.

## Sources

The rules above are drawn from primary and practitioner sources, verified against
each other:

- **Reversible vs irreversible / two-way vs one-way door** (Bezos's Amazon
  shareholder letters, via): Farnam Street — <https://fs.blog/reversible-irreversible-decisions/> ·
  thoughtbot — <https://thoughtbot.com/blog/one-way-vs-two-way-door-decisions> ·
  <https://thynkiq.com/blog/reversible-vs-irreversible-decisions>
- **The reversibility framework has limits (reversibility decays over time):**
  <https://saeedhbi.medium.com/reversibility-decays-what-bezoss-framework-misses-about-technical-decisions-bf217cd2de49>
- **HITL contact types (Approval / Input / Escalation) + batching:**
  <https://understandingdata.com/posts/human-in-the-loop-patterns/> ·
  <https://galileo.ai/blog/human-in-the-loop-agent-oversight>
- **Per-action interrupt policy (LangChain HumanInTheLoopMiddleware `interrupt_on`,
  argument-conditional `when` predicate):**
  <https://docs.langchain.com/oss/python/langchain/human-in-the-loop>
- **SRE alerting discipline — burn-rate tiering, precision/recall:** Google SRE
  Workbook — <https://sre.google/workbook/alerting-on-slos/>
- **The judgment gap + Ask-F1 dual-penalty metric:** HiL-Bench —
  <https://arxiv.org/pdf/2604.09408>
- **Calibration, misuse/disuse, automation complacency:**
  <https://galileo.ai/blog/human-in-the-loop-agent-oversight> ·
  Parasuraman & Riley (1997) on automation misuse/disuse.

A confidence-threshold-*only* routing policy was **refuted** in this research — do
not adopt it. Reversibility is the gate; confidence rides on top.
