# Forgejo release prerequisite

Offline source fixture: base `2300f4d594b4c711f59433a8de2246a1cd6b1cf2`
refuses `release:forgejo:forge.example/team/project@v1.2.3`; source candidate
`95c797f4` accepts that same condition and reads a published in-memory release.
A draft stays unmet; a mismatched configured host remains UNKNOWN without a read.
No live HTTP, release publication, event registration or sweep occurs.

Repeat with `python3 probe.py /path/to/shantytown/resume_kinds.py`.
The probe supplies all fixture responses and checks its expected results.

Download `output.log.gz` and `timing.log`, decompress the former, then replay:

```
gunzip -k output.log.gz
scriptreplay --log-out output.log --log-timing timing.log
```

Playback verified with util-linux scriptreplay. This is a terminal recording,
not an inline video. `transcript.txt` is the readable fallback. Retained here as
small sanitized source-review evidence; deployment and natural acceptance are
not demonstrated. Later recording-only commits do not change the source behavior.
