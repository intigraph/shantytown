# Unicode quarantine literals

Replay identical fixtures against base `023868ba` and functional source
`0a357fc`. Astral characters previously became surrogate-pair escapes inside
Turtle and failed exact readback. The changed source preserves the original
code points and verifies the artifact. Quoting, backslashes, newline and a
control character still round-trip. A lone surrogate remains refused before
any journal or write, now with a controlled error.

[Recording output](quarantine-unicode.output),
[timing](quarantine-unicode.timing), [reproducer](quarantine-unicode.py).
Download the recording pair to replay:

```sh
scriptreplay --log-out quarantine-unicode.output --log-timing quarantine-unicode.timing
python3 quarantine-unicode.py --source /path/to/source-checkout
```

Playback verified with util-linux scriptreplay. The reproducer requires the
existing test extra (`rdflib`). The server is an isolated fixture, but the
serializer and RDF parser execute normally. No live model or graph write is
performed. This demonstrates source behavior; installation remains separate.
