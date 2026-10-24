# Routine inbox batch demonstration

Without the explicit routine option, durable inbox delivery still persists and
submits immediately. With routine batching admitted for a scoped administrator,
two persisted progress pointers produce no early submission, one batch on the
eligible tick, and no second submission. Each original sender prefix survives.

[Actual output](output.txt) was recorded from engine source `1148c5fa1fcbea5d`:

```sh
PYTHONPATH=. python3 docs/demos/admin-routine-inbox/demo.py
```

The demonstration uses real private file-inbox persistence and acknowledgements,
with a synthetic clock, pane and admitted policy. It does not configure a live
administrator, run a real schedule, change a session or measure account spend.
The later demo-asset commit leaves tested engine source unchanged. Tests also
cover OFF/unknown policy, recipient binding changes, ambiguous submission,
stranded input and failed acknowledgement; those cases retain durable pointers.
