# Reviewer reservation on the seed

The reservation is one `reviewer:<crew-name>` label on the Seeds item. It
survives head refreshes and a successor attached to the same item. A split
child can inherit it explicitly:

```sh
st work item review-reservation task-1 --reviewer peer --dry-run
st work item review-reservation task-1 --reviewer peer
st work item review-reservation task-1
st work item review-reservation task-2 --inherit-from task-1
```

Pass each folded author with `--contributor NAME`; the current item assignee
is also excluded. Reassigning a different reviewer requires the exact old
name with `--replace-reviewer OLD`, and retains the transition in a comment.
Existing reservations are never silently replaced. A competing revision
refuses the write. A failed or uncertain write must be read back before retry.
Other labels, ownership, work status and dependency gates are preserved.

This is the first slice of PR lineage support: explicit reservation storage
and inheritance. It does not dispatch a reviewer, approve a PR, or change
the automatic review router. Publish-time lineage and claim-time warnings
follow separately. Existing reservations in item comments are not migrated
automatically.

The source fixture demonstration is repeatable with:

```sh
PYTHONPATH=. python3 docs/probes/reviewer-reservation/demo.py
```

It uses the actual command parser and reservation handler with a synthetic
Seeds adapter. No production item is read or written. Watch the same peer
inheritance, the second-peer refusal, and preservation of an external gate.

[Recorded terminal output](output.log) and [timing](timing.log) retain the
real fixture responses. Download both and replay with
`scriptreplay --log-out output.log --log-timing timing.log`.
The recording demonstrates candidate source behavior, not installed acceptance.
Its base is `fabab2e3330f65e3bd2f2fe30b4faa9a042f144a`; the candidate is the
commit containing this directory. This is a new command; the base has no
reservation action.
