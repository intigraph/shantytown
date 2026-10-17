# Pending-event work does not mean free capacity

Run from the checkout with Python 3.11 or newer:

```sh
python3 docs/probes/event-waiting/demo.py --baseline-ref 4b48bce --output /tmp/waiting-output.json
```

This archives the baseline into a temporary directory and invokes the same
private fixture against both source trees. Worker liveness, wiring and the unrelated unassigned pool are controlled.
The real free-worker selector reads private Files tracker metadata, applies the
shared waiting predicate, and passes its result through the feed gate and
stop-policy decision. Native Seeds projection is covered separately by tests. No service call, dispatch, installed
hook execution or runtime configuration change occurs.

Ten identical synthetic admin turns produce ten dispatch blocks before the fix
and zero while an agent owns externally gated work with a review time two hours away. The existing fifteen-minute waiting control
stays at zero blocks. A truly idle worker still produces ten blocks. Epic and parked
candidates go from two offered items to zero; owned and human-only controls stay
excluded. Titles do not establish work type or manual authority.

[output.json](output.json) retains both results. These counts are deterministic
policy decisions, not an observed production notification rate. Review boundary,
partial read, expiry and status-change controls live in the test suite.

Download [recording.log](recording.log) and [timing.log](timing.log), then replay:

```sh
scriptreplay --log-out recording.log --log-timing timing.log
```
