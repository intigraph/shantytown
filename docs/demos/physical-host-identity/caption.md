# Physical host identity across a private display hostname

The same library fixture runs against base `00aeb887d5ec2f8575283bd1c8eca5bbf09aa795`
and behavior head `3493d7c2b547127d9dde03e60c02341712f3229d`.
It mocks the kernel hostname as `ada` after capturing `Host-A.example`.
No actual namespace, daemon, enrollment, graph write or network request runs.

Before: the lifecycle producer changes, Quipu read/write attribution becomes
`ada`, and both governor telemetry groups use instance `ada`.
After: the original producer survives, Quipu retains the original host spelling
(with the existing read-context lowercase normalization), and both telemetry
groups retain `Host-A`. An actual fake tool child changes from an unset
`QUIPU_HOST` to the captured original host, so standard stack subprocesses
inherit the same attribution. Removing the pin after leaving the namespace preserves
the original producer in both revisions.

[Raw terminal recording](output.log) and [timing](timing.log) are small retained
repository artifacts. Download both and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was verified with util-linux scriptreplay. The raw recording is also a
readable transcript; no inline video playback is claimed. Reproduce against each
checkout by setting `PYTHONPATH` to that checkout and running [demo.py](demo.py).
The recording commit changes only documentation/recording bytes after the named
behavior head; the demonstrated behavior is unchanged.

The 339-test focused qualification includes retained-head/receipt continuity,
foreign-host refusal, malformed-pin refusal, local/off-host inbox and governor
census behavior. All passed, with one existing skip, under the HOME
escape guard. This is source qualification, not namespace permission, actual
Remote Control advertised naming, retained pairing, or phone acceptance.
