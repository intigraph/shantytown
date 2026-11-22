# Protected endpoint fixture demonstration

Before this change (base `12d768d5`), the signed transport required an already
connected channel; there was no protected endpoint client. The new entry starts
with activation OFF. In the recording it refuses immediately, then an explicitly
enabled private fixture delivers one signed frame and receives
`{"live":false,"state":"prepared"}`. A wrong peer UID receives zero request bytes.

Root enrollment, protected descriptor and socket metadata are synthetic. The
Unix connection, peer credentials, Ed25519 signature and SQLite nonce ledger are
real. This exercises a library boundary; it does not install a listener, connect
to production, launch a job or prove runtime activation.

Run from the repository root with test dependencies installed:

```sh
python3 docs/demos/recruit-protected-endpoint/run.py
scriptreplay --log-out docs/demos/recruit-protected-endpoint/output.log --log-timing docs/demos/recruit-protected-endpoint/timing.log
```

The output/timing pair is a terminal recording, not a video. `output.log` is also
the readable transcript. The final assertion checks the zero-byte refusal.
