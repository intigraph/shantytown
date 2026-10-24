# Work classes and harness routing

Work-class admission is disabled by default. To enable it in a reviewed
configuration, set `admit_class = true` under `[governor]`. This switch changes
item eligibility, not usage limits, harnesses, or agent roles.

The exact tracker item supplies its labels. `work:design` and
`work:important-quipu-code` select the Claude authoring lane. The latter is the
Quipu-specific class; no repository field or title inference is used. Every
other class selects Codex, including generic `work:important-code`, docs,
unlabelled items, and missing or unreadable labels. An unreadable class reports
that reason rather than treating a ready-list label as permission.

Explicit `st go` targets must match the selected lane. A mismatch refuses before
assignment or pane delivery, leaving the target and its harness unchanged.
Scheduled feed candidates and assigned-haul checks use the same predicate and
read the authoritative item. A missing matching worker does not authorize a
fallback to the other harness. Existing active work keeps its continuation
semantics.

`st sling` remains the executive design hand-off: it records the design and
notifies the executive, without assigning a worker. A later `st go` follows the
same class rule as any other dispatch.

`class_exempt = ["lead-name"]` can exempt explicitly named lead, administrator or keeper
cards from this filter only. Listing a worker does not exempt it. Usage freezes,
drains, priority floors, maintenance and other dispatch holds remain in force.
The existing `exempt` priority-floor setting does not waive work-class admission.

This is an authoring filter, not review routing. Reviews still require an
independent non-author Codex reviewer through the normal review process.

## Synthetic demonstration

The [terminal recording](demos/work-class.cast) and
[plain transcript](demos/work-class.txt) show the same ordinary, design, and
important-Quipu fixture items through `Verdict.admits` on base `b485f80a` and the
candidate. The base has no class filter; the candidate explicitly enables it.
Ordinary work now refuses Claude and admits Codex; the two admitted classes
select Claude and refuse an explicit Codex target. Key-off compatibility is
covered separately by the real CLI tests.

Run `python docs/demos/work-class.py` against each checkout to repeat the
read-only library demonstration. The recording contains actual subprocess
output in asciinema v2 format; download it to use a compatible terminal player.
It demonstrates source behavior, not a live deployment or scheduler run.
The small recording and transcript stay with this documentation in Git.
