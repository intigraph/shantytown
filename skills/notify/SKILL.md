---
name: notify
description: >-
  Push a message to a human — and report honestly whether it left the machine.
  Use this skill when asked to "notify", "alert me", "page someone", "send to
  chat", "ntfy", "post to the channel", "escalate", or at the end of a patrol,
  deploy, or long-running job that a person needs to hear about. Covers severity
  routing, ntfy push, generic JSON webhooks (Slack / Mattermost / Discord / an
  IRC bridge), and the difference between accepted, delivered, and read.
  Portable: shell + HTTP, plus a stdlib Python engine. No bot, no daemon, no
  persistent connection.
allowed-tools:
  - Bash
  - Read
---

# notify — say it left the machine, or say it didn't

**Stack tools this reaches for**

| Present | This skill uses it for | Absent — what happens |
|---|---|---|
| **[ntfy](https://ntfy.sh)** (`${NTFY_URL}` + `${NTFY_TOPIC}`) | phone push, severity → priority | transport skipped; if it was the only one, exit `3` and **nothing is sent** |
| **Any JSON webhook** (`${NOTIFY_WEBHOOK_URL}`) | Slack / Mattermost / Discord / your own IRC bridge | same — skipped and counted, never silently ignored |
| **[metrics-query](../metrics-query/SKILL.md)** | the finding being sent | you supply the body yourself |
| **[homelab-patrol](../homelab-patrol/SKILL.md)** | end-of-patrol report | — |

Both transports are plain HTTP POST against public, documented services. There
is no bot to run and no session to keep alive.

**On IRC:** skein deliberately ships no IRC client. IRC needs a *persistent
connection*, and a persistent connection is a daemon — the one thing this repo
does not do. If you want IRC, run a bridge (matterbridge, an ntfy→IRC relay,
a webhook-to-`ii` script) and point `NOTIFY_WEBHOOK_URL` at it. That is an
honest boundary, not a missing feature.

## The one rule that matters

**Accepted is not delivered. Delivered is not read.**

An HTTP 200 from a push server means the server took the bytes. It does not mean
a phone buzzed, it does not mean the topic had a subscriber, and it does not mean
a person looked. Every success message this tool prints says **ACCEPTED**, and
the summary line says so out loud, because "I notified the team" is one of the
easiest false claims an agent can make and one of the most expensive.

The corollary is worse, and it is why the skill exists:

> **A notifier with no transport configured looks exactly like a working one.**
> It returns instantly, prints nothing alarming, and an escalation policy built
> on it stays green for months — until the night it is needed.

So "nothing was configured" gets **its own exit code**, and it is never `0`:

| exit | meaning |
|---:|---|
| `0` | **DELIVERED** — every configured transport accepted it |
| `1` | **PARTIAL** — at least one accepted, at least one failed |
| `2` | **FAILED** — transports were configured and *all* of them failed |
| `3` | **UNCONFIG** — no transport configured, or suppressed by severity. **Nothing was sent.** |

`2` and `3` are different on purpose: one is an outage, the other is a missing
line in your env file, and the fixes have nothing in common.

## Step 1 — the case you must see once

Run it with nothing configured, deliberately, before you trust it:

```text
$ python3 notify.py "disk 92% on host-b"
NOTHING WAS SENT — no transport is configured.
  Set NTFY_URL + NTFY_TOPIC, and/or NOTIFY_WEBHOOK_URL.
  This is exit 3, never 0: an escalation path with no transport behind it
  is not a quiet success, it is the outage you find out about tomorrow.
$ echo $?
3
```

If your wrapper turns that into "notification sent", stop and fix the wrapper.

## Step 2 — send something

```text
$ python3 notify.py -s critical "db is down"
ntfy       FAILED    http://127.0.0.1:1/ops unreachable: <urlopen error [Errno 111] Connection refused>

0/1 transport(s) ACCEPTED the message. 'Accepted' means the server took it — not that a human read it.
$ echo $?
2
```

Each transport reports its own outcome on its own line. There is no blanket
"sent" — a two-transport send where one fails is `PARTIAL`, and you can see
which one.

`--dry-run` shows the plan and touches nothing:

```text
$ python3 notify.py -n -s warning -t "patrol: host-b" -f report.md
ntfy       PLANNED   would POST https://ntfy.example.com/ops priority=4 (74B)
webhook    PLANNED   would POST https://chat.example.com/hooks/ops key='text' (112B)

2 transport(s) would be attempted. NOTHING WAS SENT.
```

Note it prints `PLANNED`, not `ACCEPTED`. A dry run has accepted nothing, and
the word is the whole thing this tool is careful about.

## Step 3 — write the body to a file, not into a double-quoted string

```bash
cat > /tmp/report.md <<'EOF'          # the QUOTED 'EOF' disables ALL substitution
host-b / at 92%. Growth is the `journalctl` spool; $(du -sh /var/log) confirms.
EOF
python3 notify.py -s warning -t "patrol: host-b" --file /tmp/report.md
```

**Your shell expands backticks and `$(...)` inside double quotes before `notify`
ever runs.** Incident reports quote commands constantly, so this is not a corner
case — it is the normal content of the normal message. Both failure modes are
quiet: the text either *executes*, or is *deleted while the send reports
success*, and the remaining sentence usually still scans, so nobody can tell.

`--file` and stdin are inert. `notify.py` never re-interprets the body — a test
asserts that backticks arrive as backticks.

## Severity, and what it actually controls

`-s debug|info|warning|critical` maps to an ntfy priority (1/3/4/5 by default,
each overridable) and is prefixed to the webhook payload.

```bash
export NOTIFY_MIN_SEVERITY=warning     # drop anything below this
```

Suppression by `NOTIFY_MIN_SEVERITY` exits **`3`, not `0`** — because a message
you decided not to send is still a message that was not sent, and a caller that
records "notified" off it has recorded a fiction.

**Set a severity floor deliberately, and then read the floor at least once a
quarter.** A threshold raised during one noisy incident and never lowered is
indistinguishable from a working alert path.

## Prove it can fail

A check that has never returned red isn't a check. All four outcomes plus the
payload rules are exercised in `test_notify.py`:

```bash
python3 -m unittest    # in this skill's directory
```

To force each for real:

| Outcome | How to force it |
|---|---|
| `UNCONFIG` (3) | `env -u NTFY_URL -u NOTIFY_WEBHOOK_URL python3 notify.py hi` |
| `FAILED` (2) | `NTFY_URL=http://127.0.0.1:1 NTFY_TOPIC=x python3 notify.py hi` |
| `PARTIAL` (1) | configure a good ntfy and a bogus `NOTIFY_WEBHOOK_URL` |
| `DELIVERED` (0) | a real topic — then **subscribe and confirm it arrived**, once |

That last one is the only test of the actual claim. Do it once per environment.
Everything else proves the tool behaves; only a subscriber proves the path works.

## Configure (config, not constants)

```bash
export NTFY_URL=https://ntfy.example.com      # ntfy server base (ntfy.sh works)
export NTFY_TOPIC=ops-alerts                  # both are required, or ntfy is skipped
export NTFY_TOKEN=tk_...                      # optional: Authorization: Bearer
export NOTIFY_WEBHOOK_URL=https://chat.example.com/hooks/xxx
export NOTIFY_WEBHOOK_KEY=text                # "text" Slack/Mattermost, "content" Discord
export NOTIFY_MIN_SEVERITY=info               # debug|info|warning|critical
export NOTIFY_PRIORITY_CRITICAL=5             # override any severity→priority mapping
export NOTIFY_TIMEOUT=10
```

Nothing is hardcoded. A topic without a URL is **not** a transport — it is
skipped and counted as unconfigured, because half a config is the most
convincing way to have no alerting at all.

## Anti-patterns

- **Reporting "the team was notified" off exit `0`.** Say "accepted by ntfy".
  The distinction costs one word and is the difference between a status report
  and a guess.
- **Wrapping this in `|| true`.** That converts all four outcomes into success.
  If a failed page must not fail the job, branch on the exit code and *record*
  the failure — don't erase it.
- **Paging on everything.** An alert channel nobody can keep up with is a channel
  nobody reads, which is the same as no channel — but with the paperwork of one.
- **Assuming the channel is reachable from where the reader is.** A LAN-only push
  server cannot reach a phone that is not on the LAN. That is a real, common, and
  completely invisible gap: every send returns `0` forever.
