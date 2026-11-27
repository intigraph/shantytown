# za4f.6.1 demo: a verified triage report becomes journaled shadow intents once

Before (unchanged tree, base `daa0fe24`): `shantytown/incident_consumer.py` does not exist, so a verified
report has no consumer: `python -c "import shantytown.incident_consumer"` raises `ModuleNotFoundError`
and #678's validator and planner are called by nothing.

After: `PYTHONPATH=. python docs/probes/incident-consumer/demo.py` (recorded in `demo.txt`). The same event
twice gives the same two shadow intents and ONE journal file; a report about another incident, an
unverified record and a changed report for the same run are each refused, and the journal stays at one file.
Synthetic fixtures only; nothing is launched, signed, queued or sent.
