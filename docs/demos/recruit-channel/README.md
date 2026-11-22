# Connected controller preparation

Base `9d5ca5d2` provides a bounded client exchange but no receiving preparation
adapter. Source implementation `011ddf26` authenticates the independent
controller before input, checks the peer against its protected recruiter UID,
reads one bounded frame and rechecks the binding. It then calls the existing
signed-request verifier, durable nonce store and planner. Watch the socket
response match the prepared receipt, and a new connection with the same signed
frame refuse replay after reopening the store.

Run `python3 docs/demos/recruit-channel/run.py`. Read [output.log](output.log),
or download this directory and replay:

```sh
scriptreplay --log-timing timing.log --log-out output.log
```

The following recording/documentation commit preserves the implementation bytes.
The small recording follows the existing repository demo retention layout.

Positive controls explicitly substitute protected peer enrollment, outer fixture
ancestry, key/custody/forge and capability. Sockets, SQLite state and the planner
are real. Tests separately show actual kernel peer credentials refusing before
input when they do not match the protected UID. No real identity policy is
installed, and no privilege, native UID probe or job launch occurs.

The I/O deadline includes time spent in existing admission but cannot cancel
admission. A late preparation may finish durably after the client times out;
the adapter refuses its late reply and retains the state. Lost replies likewise
leave the original nonce and prepared operation consumed. Neither case retries
or converts a prepared observation into execution authority. Preparation uses
the existing admission adapter ceilings. This adapter writes no raw refusal or
exception text to the channel.

There is no listener, endpoint selection, CLI wiring or installation in this
slice. The existing live recruiter refusal remains. The eventual endpoint must
be installed and wired through the separately gated activation path. Actual
launch requires re-entering its current gates; prepared receipts are never
leases. Only the existing launch-review preparation path is exposed here;
merge recruitment remains off.
