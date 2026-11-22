# Triage report shadow demonstration

This new library has no API on base46035d04. In the candidate source checkout,
a complete synthetic diagnosis yields two shadow intents; partial coverage
refuses that diagnosis; an unknown verdict yields no intents. Mutating the
caller dictionary does not rebind an earlier validated snapshot.

Run from the repository root:
`PYTHONPATH=. python3 docs/probes/incident-report/demo.py`.
The sanitized input is input.json. demo.txt and demo.time are an actual terminal
recording, replayable with `scriptreplay -t demo.time demo.txt` from this folder.
The recording covers this directory's demo and the incident_report.py source
committed with it; it makes no installed/runtime/authentication claim. No Action
executes. The signed-reader, frozen-launch binding and executor gates remain open.
