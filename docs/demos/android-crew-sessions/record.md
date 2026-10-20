# Android crew-session evidence: source and offline scope

Date: 2026-10-18 UTC. Base/source contract:
`708b0348d7ff5dbe140397b95f0b339a4c23a2b4`.
The candidate adds the [runbook](../../android-crew-sessions.md) and four
offline operator-sequence tests; production command behavior is unchanged.

## Version and coverage record

| Surface | Observation | Coverage |
| --- | --- | --- |
| Installed Shantytown | `st 0.7.1 (708b034-dirty)` | Version and non-issuing command help only; suffix retained as reported. |
| Source checkout | Clean base `708b034` before this documentation/test branch | Actual parser/dispatch and pairing implementation used by fixtures. |
| Launcher Codex CLI | `codex-cli 0.161.0` | Version read only; not the selected running server's version. |
| Selected live server | Not inspected in this source-only work | No daemon/status request, issuance or lifecycle operation. |
| Android OS/app, account/workspace, UI labels | Unavailable | No phone session, screenshots or manual-entry/QR option verified. |
| Official documentation | [Working on your phone][official], fetched 2026-10-18 | General Remote and desktop QR guidance; not per-card Android acceptance. |

The earlier `agent-remote` [fixture demo](https://github.com/scbrown/shantytown/blob/708b0348d7ff5dbe140397b95f0b339a4c23a2b4/docs/demos/agent-remote/README.md) records
the command implementation. It is not Android evidence and is not reclassified
as such by this documentation change.

## Repeat the source checks

From the checkout, using its existing test environment:

```sh
python -m pytest -q tests/test_agent_remote.py
python -m pytest -q tests/test_agent_remote.py tests/test_remote_onboarding.py
```

The first command is the unchanged before/after control (45 cases). The second
also runs four operator sequences through the real `st agent remote` parser and
dispatch with a fixture registry/provider. The added fixtures forbid socket
creation. They verify:

1. Two cards with the same computer label remain distinct; dry-run requests
   zero codes; an explicit synthetic request goes only to the selected card.
2. Inactive cards remain inactive. A later *test-input* change permits fresh
   inspection without issuance; it does not launch a daemon.
3. A generation change withholds the synthetic code. A separate dry-run does
   not retry issuance; an explicit fixture attempt uses the new generation.
4. A pairing timeout is UNKNOWN, has one request, and does not leak provider
   details. Later inspection sends no further pairing request.

Observed on the source branch, Python 3.14 / pytest 9.1.1: baseline 45 PASS;
candidate 49 PASS (the same 45 plus four new sequences). Both commands ran
through the deployment's test-HOME guard: 158 watched paths and five UID-keyed
resources unchanged. This is watched-surface evidence, not a hermeticity claim.

Fixtures model response sequences, not a provider pairing database or mobile
transport. There is no test of phone enrollment persistence, real message
delivery, approvals, daemon restart, agent cycle or host reboot. Existing
tests separately cover expired responses, wrong environment, effective harness
selection, foreign host refusal and UNIX peer identity.

## Device and lifecycle acceptance remains open

| Check | Result | Required evidence |
| --- | --- | --- |
| Android manual enrollment / exact UI labels | UNKNOWN | Authorized device run with OS/app versions and observed labels. |
| QR/app-link for a crew server | UNKNOWN | Actual supported payload and client observation; do not invent a QR. |
| Select existing intended conversation | UNKNOWN | Visible context match and harmless authorized message arriving there only. |
| Prompt delivery / approval delivery | UNKNOWN / UNKNOWN | Separate controlled observations; history browsing is insufficient. |
| Phone reconnect / agent cycle / daemon restart / host reboot | UNKNOWN for each | Owner-approved boundaries, pre/post identities and recovery outcomes. |

No live enrollment or lifecycle commands were executed for this record. The
runbook is ready to guide a separately authorized operator acceptance session;
its end-to-end Android success metric has not been measured.

**Demo unavailable:** this is a documentation/offline-fixture change with no new
runtime behavior, and phone/lifecycle execution is outside this source scope.
The rendered [runbook](../../android-crew-sessions.md), reproducible sequences
above and existing sanitized command demo are the review evidence. They are
not a recording of an Android onboarding session.

[official]: https://developers.openai.com/training/walkthroughs/working-on-your-phone
