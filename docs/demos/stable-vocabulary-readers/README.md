# Reader demonstration

Base `48bb2a84b566cf107214057c4a5e1d05a928080d` versus this source candidate.
The same private legacy and published-vocabulary WorkflowRun fixtures execute
real SPARQL: base reads 1/0 rows; candidate reads 1/1. No HTTP, graph writes,
key operations or production acceptance. Requires the declared RDF test extra.

Repeat: `python3 docs/demos/stable-vocabulary-readers/demo.py`.
Replay: `scriptreplay --log-out output.log --log-timing timing.log`.
Small sanitized output-only recording retained here because no external demo
artifact destination is established. Native signed-writer adoption remains held.
