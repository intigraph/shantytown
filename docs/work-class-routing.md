# Work classes and harness routing

Work-class admission is disabled by default. To enable it in a reviewed
configuration, set `admit_class = true` under `[governor]`. This switch changes
item eligibility, not usage limits, harnesses, or agent roles.

Codex is eligible by default for every class. The exact tracker item may admit
a Claude author only with both an operator-granted `work:claude-authorized`
label and either `work:design` or `work:important-quipu-code`. The latter covers
important Quipu code, including security work. Neither a class nor the
authorization label alone grants this exception. A `work:review` label prevents
the authoring exception. Generic `work:important-code`, docs, unlabelled items,
and missing or unreadable labels grant no Claude admission. No title,
description, priority or repository inference is used.

The operator records the explicit task ruling and provenance on the item before
granting `work:claude-authorized` through the normal governed tracker path.
Removing the label revokes the exception at the next admission check. This
filter consumes tracker metadata; it does not authenticate the person setting
labels or replace tracker write authorization. No global Claude exception or
live policy change follows from installing this source.

Explicit `st go` targets must be eligible. A mismatch refuses before
assignment or pane delivery, leaving the target and its harness unchanged.
Scheduled feed candidates and assigned-haul checks use the same predicate and
read the authoritative item. A missing matching worker does not authorize a
fallback to the other harness. Existing active work keeps its continuation
semantics.

`st sling` remains the executive design hand-off: it records the design and
notifies the executive, without assigning a worker. A later `st go` follows the
same class rule as any other dispatch.

`class_exempt = ["administrator-name"]` can exempt explicitly named actual
administrator cards from this filter only. Listing a worker, lead or keeper does not exempt it. Usage freezes,
drains, priority floors, maintenance and other dispatch holds remain in force.
The existing `exempt` priority-floor setting does not waive work-class admission.

This is an authoring filter, not review routing. Reviews still require an
independent non-author Codex reviewer through the normal review process.

## Synthetic demonstration

The historical [terminal recording](demos/work-class.cast) and
[plain transcript](demos/work-class.txt) show the same ordinary, design, and
important-Quipu fixture items through `Verdict.admits` on base `b485f80a` and the
candidate. The base has no class filter; the candidate explicitly enables it.
Ordinary work now refuses Claude and admits Codex; the two admitted classes
selected Claude and refused an explicit Codex target in that historical version.
Current admission additionally requires task authorization and keeps Codex
eligible; the historical recording is not current acceptance. Key-off compatibility is
covered separately by the real CLI tests.

Run `python docs/demos/work-class.py` against each checkout to repeat the
read-only library demonstration. The recording contains actual subprocess
output in asciinema v2 format; download it to use a compatible terminal player.
It demonstrates source behavior, not a live deployment or scheduler run.
The small recording and transcript stay with this documentation in Git.
