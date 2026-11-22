# Bounded connected controller channel

Base `6c115c7fa034d46965201f98219ef7627e5cef4b` has no connected-channel
exchange helper. Source implementation `f055157d` sends one signed review frame
over a real local Unix socket, checks the configured peer UID, half-closes the
request and receives bounded JSON under a single total deadline. The receiver
fixture calls the existing signature and nonce verifier. Watch the malformed
response become `DeliveryUnknown`, and the original nonce remain spent after
reopening the controller ledger. The helper never retries.

Run `python3 docs/demos/recruit-transport/run.py`. Read [output.log](output.log),
or download this directory and replay the recording:

```sh
scriptreplay --log-timing timing.log --log-out output.log
```

The recording uses synthetic key/custody/authority and a non-executing controller
response. Unix sockets, signature verification and SQLite nonce persistence are
real. It proves source behavior, not installed controller access or live launch.
The following documentation/recording commit does not change the implementation.

This is a library seam only. A future trusted caller must select and authenticate
the configured endpoint and controller UID; event/request bytes cannot supply
those inputs. The helper consumes a connected socket's write half and leaves
closing it to its owner. The receiver must still run the existing controller's
independent authority, binding, expiry, nonce, admission and launch gates. A JSON
response from this layer is data, never authority or proof of execution. All
post-send errors are uncertain delivery, including empty or malformed output;
retain attempt/nonce records and reconcile instead of resending.

There is no listener, endpoint installation, CLI wiring, daemon or privileged
call in this slice. The existing live recruiter refusal stays in place. Runtime
activation, controller installation and actual launch remain separately gated;
merge verbs are refused. The small recording is retained here with its source,
following the repository's existing demo layout.
