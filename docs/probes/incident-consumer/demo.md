# za4f.6.1 demo: a replayed incident_report event becomes journaled shadow intents once

Before (unchanged tree, base `daa0fe24`): `shantytown/incident_consumer.py` does not exist, so a verified
report has no consumer: `python -c "import shantytown.incident_consumer"` raises `ModuleNotFoundError`
and #678's validator and planner are called by nothing.

After: `PYTHONPATH=. python docs/probes/incident-consumer/demo.py` (recorded in `demo.txt`). The recorded
event `tests/fixtures/incident_consumer/triage-event.json` fed twice gives the same two shadow intents and ONE
intent file. A report about another incident, an unverified record (twice), a changed report for the same
run and a garbage event are each refused AND recorded: four `refusal-*.json` records (the repeated
unverified refusal is one record), holding reason and digests only. The intent journal stays at one file.
Synthetic fixtures only; nothing is launched, signed, queued or sent.
