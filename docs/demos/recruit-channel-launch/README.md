# Connected controller review launch

The [recording](output.log) and [timing](timing.log) compare parent
`7a2df4c89fbbae1a2809e5a591157afa9c1d6486` (entry unavailable) with
implementation `01113840dbc4ae3f58fcb07cb72d02c572ba28a5`.
The candidate first refuses its default-OFF gate without a channel or state
access. An explicitly enabled synthetic controller fixture then sends one real
signed envelope through a real Unix socket, protected-store admission and the
existing spawn transaction. One fixture launcher callback sees the real ledger
and card. Reopening/replaying the request refuses without another callback.

Enrollment, peer UID, forge/custody and launcher are synthetic. Signatures,
socket framing, SQLite state, planner, ledger and cards are real. No pane,
privileged helper, listener or service starts; this is candidate source evidence,
not production activation or real event-to-review acceptance.

Run `python3 docs/demos/recruit-channel-launch/run.py` from the repository.
The retained sanitized terminal recording can be replayed with:

```sh
scriptreplay --log-out docs/demos/recruit-channel-launch/output.log \
  --log-timing docs/demos/recruit-channel-launch/timing.log
```

The readable transcript is the fallback when scriptreplay is unavailable.
