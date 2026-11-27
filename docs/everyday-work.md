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

## A weekly job-hunt review

Recurring work is a job declared in Quipu and fired by Chaski, not a file with
a cron line. A job file under `.shanty/jobs/` with a `cron` or `every` trigger
is **refused**: the refusal names `st work jobs new`, and `st work jobs list`
exits 1 while the file exists (see [scheduled jobs](jobs.md)). Declaring a
weekly job is one command, and its `-n` output is the review.

This step needs a Quipu deployment with a jobs graph and write credentials.
Name the graph in `.shanty/shantytown.toml`:

```toml
[jobs]
graph = "urn:example:scheduled-jobs"   # the Quipu graph Chaski reads
```

Then preview the declaration. `-n` prints the exact Turtle and writes nothing:

```sh
st --root .shanty --backend files work jobs new job-search --weekly mon 09:00 \
    --tz America/New_York --host laptop --inbox coordinator --owner coordinator \
    --disabled -n \
    --message "Prepare a synthetic shortlist for a remote technical-writing role. List the criteria, missing information and next steps. Draft any outreach for my review; do not submit applications or send messages."
```

`--weekly DAY HH:MM` is local time in `--tz`. There is no cron syntax and no
weekday range: one command declares one weekly slot. Run the same command
without `-n` to write it. Exit 0 means it was written and read back, exit 1
means it was refused and nothing was written, and exit 2 means the outcome is
unknown, so run `work jobs list` before you retry.
`--disabled` declares a job that is listed but never fired.

The routine asks for a draft and a decision, rather than granting access to an
account. Replace the synthetic brief with the information you choose to share.

## A family-event planning checklist

A one-off request does not need a job. Send it to the agent when the plan
changes:

```sh
st --root .shanty --backend files inbox coordinator "Plan a fictional Saturday picnic for six people at Example Park. Give me a food checklist, a rain alternative and the decisions I still need to make. Do not book, purchase or contact anyone."
```

Manual and event (`on`) file jobs still load during the migration window, but
every `st work jobs` read prints a deprecation warning. Do not start new ones.

## Validate and preview

List what the jobs graph declares:

```sh
st --root .shanty --backend files work jobs list
st --root .shanty --backend files work jobs check job-search
```

Once `[jobs] graph` is set, `list` and `check` read only the graph and never
fall back to TOML. `run` and `history` refuse in graph mode: firing and its
history belong to Chaski's signed lane, which is not yet available from st.

A listed declaration proves the write and read-back. It does not prove Chaski
fired the job, an agent received the request or produced a useful answer.

## From a preview to a real routine

With a configured, running coordinator and a Chaski consumer for the jobs
graph, declare the job without `--disabled`. Chaski fires it; no host
scheduler, `st fleet tend` pass or cron entry is involved. Changing a declared
job is a separate change: `st work jobs new` refuses to replace an existing
name on the same host.

Check the receiving agent's result. A successful send is not
proof that the user saw the answer. Keep external actions, such as sending an
application or reserving a venue, subject to your explicit approval.

Event-driven file jobs, such as `gh.issue.opened` routing a new issue for
triage, are in the same migration window and described in
[scheduled jobs](jobs.md). Those sources require their own configured reader
and cursor, and setting `[jobs] graph` stops tend from running them. A generic “react to any comment”
adapter is not established by these examples.

Shantytown routes plain-language requests to an agent; these examples do not add
a conversational chat interface. A job declaration is a Quipu write, so keep
personal data out of the `--message` you declare. Select the shared vocabulary
and verify its loaded shapes, write provenance and read-back through that
integration before relying on those guarantees.
