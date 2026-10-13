# Tend closed-condition read demonstration

A deferral evaluator uses the exact status of its named `closed:` targets.
Previously each status check called full `show`, hydrating comments and dependency
information. The candidate reads only identity and status. Before release, the
sweeper still performs its full detail read, condition recheck and write readback.

Target: private read-only evaluation against a live tracker, not an installed
candidate or a full supervisor pass. Base source: `fa8543eb`; candidate source:
this proposal's `closed_status` adapter. Input: the same 437 deferral candidates,
59 distinct named conditions. Observed evaluator findings were identical.

## Captured transcript

These values are extracted from the actual probe output. The private recording
and raw query evidence remain with the work item; this sanitized transcript is
retained in Git. No terminal player or private service access is needed to read it.

```text
Read-only deferral evaluator: captured live results, not an installed fix
Base source: fa8543eb; candidate: narrow exact condition status
Candidates: 437 437
Named closed references: 59 59
before queries=925 HTTP200=925 exit=0
after queries=167 HTTP200=167 exit=0
Evaluator findings identical: True
```

Reproduce the library behavior with `python -m pytest -q
 tests/test_tend_condition_status.py` from this checkout. For a live read-only
comparison, use the same proven tracker and candidate rows in
`deferrals.evaluate(rows, clock, is_closed=callback)`: compare a cached
`br.show(tracker, id)["status"] == "closed"` callback with a cached
`tracker.closed_status(id).exact()` callback while counting `/query` requests.
Use the same clock, record all responses and compare complete findings.
Do not run the mutating supervisor for this comparison.

The measured reduction applies to this evaluator seam. It does not prove natural
adoption, total supervisor cost or an aggregate traffic target. Missing, ambiguous
or unreadable status evidence remains UNKNOWN. The deployed path still requires
scheduled adoption and a complete post-adoption observation window.
