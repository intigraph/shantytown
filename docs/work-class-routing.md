# Work classes and harness routing

Work-class admission is disabled by default. To enable it in a reviewed
configuration, set `admit_class = true` under `[governor]`. This switch changes
item eligibility, not usage limits, harnesses, or agent roles.

Claude and Codex are eligible to author every readable work class, including
unlabelled and routine items. Prefer Claude for designs and important Quipu code;
this is a preference, not a restriction on either author's eligibility.
`work:claude-authorized` is no longer required for authoring.

Reviews remain Codex-only: an exact `work:review` label refuses Claude even
alongside design, important-code or legacy authorization labels. Missing or
unreadable exact labels cannot prove that an assignment is authoring rather than
review, so refuse Claude conservatively. A readable empty label list admits both
authors. Unsupported or unknown harnesses remain refused by this predicate.
No title, description, priority or repository inference determines review status.

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
administrator cards from this filter only; it never waives the Claude review refusal. Listing a worker, lead or keeper does not exempt it. Usage freezes,
drains, priority floors, maintenance and other dispatch holds remain in force.
The existing `exempt` priority-floor setting does not waive work-class admission.

The review label enforces the harness boundary, not reviewer independence. Reviews still require an
independent non-author Codex reviewer through the normal review process.

## Synthetic demonstration

The historical [terminal recording](demos/work-class.cast) and
[plain transcript](demos/work-class.txt) show the same ordinary, design, and
important-Quipu fixture items through `Verdict.admits` on base `b485f80a` and the
candidate. The base has no class filter; the candidate explicitly enables it.
Ordinary work now refuses Claude and admits Codex; the two admitted classes
selected Claude and refused an explicit Codex target in that historical version.
The restored policy admits both authoring harnesses and keeps reviews Codex-only;
the historical recording is not current acceptance. See the current
[author/review demonstration](demos/restored-author-lanes.md). Key-off compatibility is
covered separately by the real CLI tests.

Run `python docs/demos/work-class.py` against each checkout to repeat the
read-only library demonstration. The recording contains actual subprocess
output in asciinema v2 format; download it to use a compatible terminal player.
It demonstrates source behavior, not a live deployment or scheduler run.
The small recording and transcript stay with this documentation in Git.
