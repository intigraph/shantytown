# Everyday work with one agent

Start with one administrator and a small, reviewable routine. The examples here
use synthetic requests. They prepare and preview work; they do not send email,
book an event or connect a personal account.

After [installing Shantytown](getting-started.md), create an isolated example
directory and a one-agent configuration:

```sh
mkdir everyday-demo && cd everyday-demo
st --root .shanty --backend files fleet init -y --admin coordinator --crew ""
```

This creates cards and configuration without starting an agent. Keep using this
directory and the explicit root below. For a running crew, first configure an
authenticated [harness](harnesses.md) and the tracker you intend to use.

## Where a routine lives

A recurring routine is a **job declared in Quipu**, and Chaski fires it.
Shantytown does not run cron jobs. You declare the job with one command,
`st work jobs new`, and review its dry run. There is no file to save:
job files under `.shanty/jobs/` are deprecated. A file with a `cron` or
`every` trigger is refused, and `st work jobs list` exits 1 while one exists.
[Scheduled jobs](jobs.md) has the full contract.

Name the jobs graph that this root reads and writes. Add it to
`.shanty/shantytown.toml`:

```toml
[jobs]
graph = "urn:example:everyday:jobs"
```

## A weekly job-hunt review

Preview the declaration:

```sh
st --root .shanty --backend files work jobs new job-search \
    --weekly mon 09:00 --tz America/New_York --host demo \
    --inbox coordinator --owner me --disabled -n \
    --message "Prepare a synthetic shortlist for a remote technical-writing role. List the criteria, missing information and next steps. Draft any outreach for my review; do not submit applications or send messages."
```

`-n` prints the exact Turtle declaration and writes nothing. That output is
the review: the schedule (Monday 09:00 New York time, every week), the
recipient (`urn:shantytown:inbox:coordinator`), the message and the
`enabled false` flag. `--weekly` takes one day and a local time. For a
fixed interval, use `--every 6h`. There is no cron syntax, so a
weekday-only schedule is five declarations or a different routine.

The routine asks for a draft and a decision. It does not grant access to an
account. Replace the synthetic brief with the information you choose to
share.

## A one-off family-event checklist

A plan you request once is a message, not a job:

```sh
st --root .shanty --backend files inbox -d coordinator "Plan a fictional Saturday picnic for six people at Example Park. Give me a food checklist, a rain alternative and the decisions I still need to make. Do not book, purchase or contact anyone."
```

`-d` puts it in the coordinator's durable inbox, so it waits there if the
agent is not running. Send it again when the plan changes. The older
`manual = true` job file still loads during the migration window, with a
deprecation warning. Do not start new work on it.

## Validate the declaration

The dry run already checked the job. It passed through the same reader that
`st work jobs list` uses, so a declaration the catalogue would refuse is
refused here first. A bad weekday, a time such as `25:00`, an unknown
timezone or an interval under sixty seconds exits 1 before anything is
written. A message is written as a Turtle literal, and any characters it
holds, an emoji included, round-trip unchanged.

The dry run proves the declaration and its rendering. It does not prove
that Quipu accepted the job, that Chaski fired it, or that an agent produced a
useful answer.

## From a preview to a real routine

On a deployment with Quipu write credentials, run the same command without
`-n` to write the job. Exit 0 means it was written and read back with the
same revision. Exit 1 means it was refused and nothing was written. Exit 2
means the outcome is unknown, so run `st work jobs list` before you retry.
Drop `--disabled` for a job that should fire. The command refuses to replace
a job that is already declared, so a change to an existing job is a separate,
reviewed change.

`st work jobs list` and `check` then read the job from the graph. Firing is
Chaski's: the job runs once Chaski's inbox action consumes declarations
(aegis-6vf.11). Without a reachable Quipu, `list` reports `cannot tell`
and exits 2. Exit 2 does not mean that there are no jobs.

Check the receiving agent's result. A successful send is not proof that the
user saw the answer. Keep external actions, such as sending an application or
reserving a venue, subject to your explicit approval.

Event-driven work, such as routing a new issue (`gh.issue.opened`) for
triage, still uses an event (`on`) file job during the migration window. See
[scheduled jobs](jobs.md). Those sources require their own configured reader
and cursor. Do not set `[jobs] graph` on a host whose event file jobs are
still live: graph mode stops tend from running file jobs, and the Chaski
consumer that would replace them (aegis-6vf.11) does not exist yet. A generic
“react to any comment” adapter is not established by these examples.

Shantytown routes plain-language requests to an agent. These examples do not
add a conversational chat interface. A job's message is stored in the jobs
graph, so leave out any personal data that should not be in Quipu. Before
relying on Quipu's guarantees, select the shared vocabulary and verify its
loaded shapes, write provenance and read-back.
