# Guarded agy adapter — offline source demonstration

Input: the same worker card selects `agy`. Base `b06d1ec51c2a4ba3c003bf9618b6386ce369d19b`
refuses the unknown harness. Candidate implementation
`c6310576cfee5a9be43d89246f6886510631a2e1` composes a sandboxed launch with
paid credit fallback disabled and send routing. The inverse controls show that
missing native receipt proof stays UNKNOWN, an unqualified lead stays refused,
and an exhausted quota group is not replaced by another group's available quota.

This is an offline library fixture, **not** a deployed agent or provider request.
The quota data is explicitly synthetic. It does not demonstrate TUI readiness,
composer submission, tool permissions, a published review or live end-to-end
acceptance. Later cancellation-cleanup changes preserve the shown launch/reader
behavior; their inverse fixture is in `tests/test_agy_job.py`.

[Output recording](output.log) · [Timing](timing.log) · [Reproducer](demo.py)

Download both recording files and run:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was checked with util-linux `scriptreplay`. The recording is terminal
output with timing, not an inline video. Reproduce with a source checkout:

```sh
python3 docs/pr-demos/agy-harness/demo.py /path/to/source
```

The small sanitized recording and caption are retained in this repository's
existing `docs/pr-demos` artifact destination. Private native probe payloads and
credentials are not included.
