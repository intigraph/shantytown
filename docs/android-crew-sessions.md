# Phone access to an existing Codex crew conversation

Use this runbook to identify the crew server you intend to reach, inspect it
without creating a code, and prepare a controlled Android acceptance check.
The host command workflow is covered by offline fixtures. **Android onboarding
and reconnect acceptance are still unverified.** There is no verified Android
button sequence or QR flow for a Shantytown crew server in this record.

## Prerequisites and scope

Use a Shantytown release with `st agent remote list` and `pair --dry-run`
(source contract checked at `708b034`). The selected card must resolve to Codex
in the deployment configuration and already have a running, connected Remote
Control server. Linux peer verification is required by this command. Missing
standalone packages, another platform, or an unsupported provider protocol need
operator diagnosis; these commands do not install or upgrade anything.

Keep the computer awake and online. Check the phone's account and workspace
against the intended host account before attempting enrollment. Availability
also depends on the client version, account and workspace policy. Do not change
permissions or launch an operator-held agent to make it appear on the phone.

Each crew member has a separate identity-bearing server. Pairing the ordinary
Codex host does not enroll every crew server. A shared computer label also does
not identify a crew member. Shantytown selects the explicit card name and checks
its effective harness, host and daemon identity; you do not need to inspect
runtime directories or set `CODEX_HOME` yourself.

## Discover and inspect without issuing a code

Run on the deployment that owns the selected card:

```sh
st agent remote list --json
st agent remote pair alice --dry-run --json
```

Replace `alice` with an existing card name from discovery. Compare `agent`,
`harness`, `host`, `availability` and, when supplied, `server_name`. A null host
means the deployment did not declare a local host identity; do not guess one.
`connected` describes the server's Remote Control connection, not phone access
or delivery to a conversation. Discovery can exit successfully with individual
rows unavailable or unknown: inspect the rows, not just the exit code.

Dry-run reads status and prints `action: "would_pair"` without requesting a
pairing code. It is not a preview of the Android UI and does not prove that
enrollment would succeed. Neither discovery nor dry-run starts a stopped card.

## Manual code: an explicit operator action

Only when enrollment is authorized and the intended operator is ready:

```sh
st agent remote pair alice
```

The result includes a short-lived manual code and an expiration in UTC. Show it
directly to that operator. Do not pipe it into a log, issue, inbox, recording or
QR generator; `--json` is secret-bearing too. Do not publish even an expired
code as evidence. The command has no QR output mode or documented app-link
payload; do not manufacture either from the manual code.

The official [Working on your phone][phone] guide describes desktop QR setup
and general Remote use. It does not establish the manual-entry labels for this
per-card Linux/Android path. If the Android build offers a manual-code path,
record its actual labels and version during authorized acceptance. If it does
not, mark that case unsupported or unavailable and stop rather than borrowing
an unverified button sequence. No Android labels have been observed here.

Issuance is not enrollment. After an authorized connection, select the intended
**existing** crew conversation. Do not create a new crew agent or conversation
as a substitute. First compare visible conversation context without sending.
Then, only with operator approval, send a unique harmless test message and
verify its arrival in that same host conversation. Check another crew member
did not receive it. Viewing history alone does not prove prompt delivery.
Approval delivery needs its own controlled, harmless approval request; a sent
prompt is not evidence that approvals work. Existing permissions still apply.

## Failures and recovery

| Observation | Safe next step | What it does not prove |
| --- | --- | --- |
| Desired card missing from list | Check the deployment and registry with its owner. | Ordinary-host pairing does not substitute for the missing card. |
| `inactive` | Leave it stopped; ask its owner about the next authorized launch. | Discovery is not a lifecycle request. |
| `disabled`, `connecting` or `errored` | Record the safe status; ask the owner to diagnose configuration or connectivity. | `pair` will not enable or start Remote Control. |
| `unavailable` or `unknown` | Read the safe diagnostic; check effective harness, host ownership, version and account policy. | Empty output is not absence or permission to weaken identity checks. |
| Several cards share `server_name` | Select by explicit card name; verify the intended conversation separately. | A computer label is not selected-agent delivery. |
| Expired or rejected manual code | Rediscover the selected card; request one fresh code only when explicitly authorized. | A code expiring does not prove existing pairings were revoked. |
| Timeout during pairing | Preserve outcome UNKNOWN; do not automatically retry. | A timeout may follow issuance; it is not proof nothing happened. |
| Daemon generation or environment changes during a request | Output is withheld; rediscover before a separately authorized attempt. | A prior code is not evidence for the replacement server. |
| Wrong account/workspace or no usable Android enrollment option | Stop enrollment and check the client/account with its owner. | A connected host does not prove mobile entitlement or compatibility. |

`--timeout` accepts 0.1–30 seconds (default three) per card. Increasing it is
not recovery from a wrong identity or missing feature. Do not loop pairing
requests, copy credentials between runtime homes, or restart another card.

## Reconnect and lifecycle acceptance

The offline fixture changes provider state to test refusal and rediscovery.
It does **not** cycle an agent, restart a daemon, reboot a host, connect a phone
or model the provider's pairing store. No persistence guarantee follows.

| Boundary | Measured here | Later acceptance, at a separately authorized safe boundary |
| --- | --- | --- |
| Phone disconnect/reconnect | Unavailable | Return to the same existing conversation; verify history, then authorized prompt delivery. |
| Normal `st agent cycle` | Unavailable | Record pre/post card and conversation identity, whether enrollment survives, and any recovery required. |
| Daemon restart | Unavailable | Record whether the existing phone enrollment survives; rediscover before any new code. |
| Host reboot | Unavailable | Verify normal crew recovery first, then selected conversation and phone delivery. |

Do not restart active crew to fill this table. Schedule a fixture agent or a
normal owner-approved boundary. If access is lost, inspect with `list` and
`pair --dry-run` first; re-enroll only after explicit authorization. Starting a
new conversation is not proof that an old one reconnected.

## Evidence and reproducible offline checks

See the [dated acceptance record](demos/android-crew-sessions/record.md).
The fixtures use the real command parser and dispatch with synthetic providers.
They cover explicit routing with duplicate labels, dry-run, stale output,
generation changes and manual rediscovery. They never contact a real daemon.

For later device acceptance, record UTC time, source revision, installed `st`,
launcher CLI, actual selected server and Android OS/app versions; the tested
account/workspace match (without identifiers); exact observed UI labels; card
and conversation selection; prompt and approval outcomes; and each lifecycle
case as PASS, FAIL or UNKNOWN with its observable evidence. Keep credentials
and private conversation content out of the record.

[phone]: https://developers.openai.com/training/walkthroughs/working-on-your-phone
