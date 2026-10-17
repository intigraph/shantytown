# Everyday work with one agent

Start with one administrator and a small, reviewable routine. The examples here
use synthetic requests. They prepare and preview work; they do not send email,
book an event or connect a personal account.

After [installing Shantytown](getting-started.md), create an isolated example
directory and a one-agent configuration:

```sh
mkdir everyday-demo && cd everyday-demo
st --root .shanty --backend files fleet init -y --admin coordinator --crew ""
mkdir -p .shanty/jobs
```

This creates cards and configuration without starting an agent. Keep using this
directory and the explicit root below. For a running crew, first configure an
authenticated [harness](harnesses.md) and the tracker you intend to use.

## A weekday job-hunt review

Save this as `.shanty/jobs/job-search.toml`:

```toml
description = "Prepare a weekday job-search shortlist"
enabled = false

[trigger]
cron = "0 9 * * mon-fri"

[action]
inbox = "coordinator"
message = "For {{date}}, prepare a synthetic shortlist for a remote technical-writing role. List the criteria, missing information and next steps. Draft any outreach for my review; do not submit applications or send messages."
```

The routine asks for a draft and a decision, rather than granting access to an
account. Replace the synthetic brief with the information you choose to share.

## A family-event planning checklist

Save this as `.shanty/jobs/family-plan.toml`:

```toml
description = "Prepare a fictional family picnic checklist"
enabled = false

[trigger]
manual = true

[action]
inbox = "coordinator"
message = "Plan a fictional Saturday picnic for six people at Example Park. Give me a food checklist, a rain alternative and the decisions I still need to make. Do not book, purchase or contact anyone."
```

Use this once when the plan changes. It does not need a recurring timer.

## Validate and preview

Both examples are disabled. List them and render each request without delivering
it to an agent:

```sh
st --root .shanty --backend files work jobs list
st --root .shanty --backend files work jobs run job-search -n
st --root .shanty --backend files work jobs run family-plan -n
st --root .shanty --backend files work jobs history
```

The list should show both names as disabled and never run. The previews should
show the recipient and rendered message, including today's date for job-search.
History should report no runs. An invalid cron such as `61 9 * * *` is refused;
do not enable a declaration until the list validates it.

These previews prove the declaration and rendering paths. They do not prove an
agent received the request or produced a useful answer.

## From a preview to a real routine

With a configured, running coordinator, change the selected file to
`enabled = true`. For the manual checklist, `work jobs run family-plan`
delivers it once; removing `-n` is an actual delivery. For the weekday routine,
arrange regular `st fleet tend` passes through your host scheduler as described
in [scheduled jobs](jobs.md). A cron uses host-local time and runs on a tend
pass, so it can arrive later than its nominal minute.

Check job history and the receiving agent's result. A successful send is not
proof that the user saw the answer. Keep external actions, such as sending an
application or reserving a venue, subject to your explicit approval.

For event-driven work, reuse the supported sources in [scheduled jobs](jobs.md):
for example, `gh.issue.opened` can route a new issue for triage. Those sources
require their own configured reader and cursor. A generic “react to any comment”
adapter is not established by these examples.

Shantytown routes plain-language requests to an agent; these examples do not add
a conversational chat interface. Local TOML jobs also do not turn personal data
into governed Quipu facts. If you enable Quipu, select the shared vocabulary and
verify its loaded shapes, write provenance and read-back through that
integration before relying on those guarantees.
