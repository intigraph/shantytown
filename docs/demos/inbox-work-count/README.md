# Messages are not ready work

The same six-row fixture contains two work items and four current/legacy message
titles, including leading whitespace. One real work item carries an `inbox`
label. At base `2f889a20bdda611609edeb6f7f2f0f0dc31ebfae`, native and legacy
utilization count all six rows, and triage offers message titles. Candidate
runtime `93b4d7a7b9b617c63674b2ad4deb9363fc8d2413` counts two work rows and
triages only work; the inbox-labeled work item remains included.

[Recorded output](output.log) and [timing](timing.log) are retained in Git.
Playback with `scriptreplay --log-out output.log --log-timing timing.log` was
verified. Extract the base's `shantytown` directory into an isolated directory,
set `DEMO_BASE_SOURCE` to it, then run `sh docs/demos/inbox-work-count/run.sh`.
The development fixture requires rdflib; it executes the actual generated
SPARQL against a local dataset and uses an isolated legacy-adapter callback.
It does not prove installed acceptance or retire any live message.
