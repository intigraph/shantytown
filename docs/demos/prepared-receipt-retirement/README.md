# Explicit retirement of a prepared dispatch

The same disposable file-backed task receives an unobserved send, one refused
retry, then explicit receipt retirement. Watch `retirement` change from
`REFUSED` to `superseded`: no text is sent and no item field changes during
retirement. The old receipt remains unauthorized. A later normal dispatch gets
a new receipt and can become authorized after observed submission and assignment.

Baseline source is `7852a0dc84ce4c194cd6868d38064f65e409e9e9`; candidate source
is the checkout containing this demonstration. Both use the real dispatch
coordinator and file tracker. The pane adapter deliberately returns no submission
witness for the first send. This is a library fixture, not a live Codex session,
production tracker mutation or installed acceptance. The separate regression
uses the real Codex transport against idle/typed/queued terminal frames.

Repeat from the repository root:

```sh
python3 docs/demos/prepared-receipt-retirement/reproduce.py
```

Download the [actual output recording](output.log), [timing](timing.log) and
[readable transcript](transcript.txt). Replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Local replay was checked; no inline player is claimed. These small sanitized
artifacts use the repository's existing `docs/demos` retention. The candidate
source was run under the HOME-escape guard. This does not prove historical
non-delivery, authorize replay of the old ID, clear any composer, or weaken the
newer-native-release requirement for an uncertain assignment.
