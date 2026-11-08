# A reminder slot before slow cycle work

A 39.4-second inbox recovery followed by a 98.6-second requested cycle exceeded
the unchanged 120-second admission budget. The scheduled overdue phase was then
skipped. Rotation eventually reached it, but did not give each scheduled pass a
reminder slot.

The shared overdue/spec/unlock notifier now runs first in the best-effort layer,
after supervision and fleet-owner admission. It keeps the other sweeps' saved
rotation cursor. The same time budget, in-flight completion, cycle custody and
notification receipt fences still apply. A disabled notifier or a non-owner host
does not acquire a new sender. No scheduler or delivery retry is added.

[Actual recording](demo.cast) · [transcript](transcript.txt). Download the cast for
an asciinema-compatible player; inline playback is unverified.

Run `python3 docs/demos/overdue-service/reproduce.py` from a checkout with pytest.
It runs identical controls against base `01f983b4` and the candidate. The base
fails two controls and passes the budget control; the candidate passes all three.
The actual tend code uses private files and mocked phase durations; no real
service, crew lifecycle, network request or notification is invoked.

This proves source scheduling behavior. Acceptance still requires an original
scheduled terminal delivery receipt, measured body bytes and phase latency.
Rollback is a normal source revert and projection; retain scheduling and receipt
state rather than editing them to manufacture another delivery.
