# Read both inbox prefixes in one native projection

Run `PYTHONPATH=. python docs/probes/pr-demos/inbox-projection/probe.py` with
`quipu-server` and `sd` on PATH (or set `QUIPU_SERVER_BIN` and `SD_BIN`).
The probe starts a disposable loopback Quipu fixture and counting proxy, inserts
modern and legacy unread messages plus ordinary-work and closed-receipt controls,
and compares the SDK reader with the native reader. Both fixture processes stop
before the probe exits. It does not query a production server.

Measured result: SDK **14 queries**, native **4 queries**, same two unread IDs
([result.json](result.json)). The fixture supplies the same explicit store proof to both readers, so these
counts exclude store-location discovery. The native path reads both prefixes and both graphs
together, without SDK issue hydration. It retains store-format and owner-shape
checks. The tests separately cover closed receipt lookup, both owner spellings,
foreign rows, disappearance, contradictory metadata and unavailable reads.

This is command-level proof. It does not establish a fleet query rate, production
latency, successful dispatch, or deployment acceptance. Those require observation
after normal installation. No cross-event cache or admission timeout change is
part of this change.

Replay the retained terminal capture with
`scriptreplay -t timing.log output.log` from this directory.
