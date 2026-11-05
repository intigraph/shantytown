# Scheduled job store outage

Trigger: an enabled durable inbox job runs without Seeds routing, then its
action fails against an unavailable fixture backend. Both revisions receive the
same private fixture through tmux run-shell on an isolated socket and minimal
environment. The action failure is injected; the check, retry terminal state,
event persistence and administrator routing use the real source implementation.

Base 2ba4862f313ae153d4baf6851d09bd8422d34c57 reports a healthy check (exit 0)
and leaves no administrator event. The candidate reports check exit 2 and
persists one actionable job-failed event independent of the work store.
The missing route remains refused in both versions: no ontology URL is guessed
as a work board.

Download output.log and timing.log and replay with:
    scriptreplay --log-out output.log --log-timing timing.log
The readable output is also a transcript. Playback requires a terminal replay
tool; inline playback is not promised. The small recording is retained here
with the source, with no external artifact service.

Reproduce by extracting the base shantytown package to a private directory,
then from the candidate checkout run:
    python3 docs/demos/job-store/record.py /path/to/private-base .
Only the two explicitly created sockets are terminated.

The demonstrated candidate code is identified by the functional source commit
in the PR body. The recording adds no runtime scheduler and does not exercise
a live host or inbox. Separate guarded tests use a real private Seeds SDK store
for successful inbox delivery, reject a missing store, drain one block-protocol
notice, and verify crash replay does not resurrect it. Installed config,
administrator drain wiring and real arrival remain separate acceptance.
