# Recover the same workspace memory at Codex startup

The [recording](recording.txt) and [timing](timing.txt) show the same synthetic
memory index on the base and candidate source checkouts. The original emitted
Codex SessionStart command omits it; the candidate includes both the memory and
its latest directive. The anchor positive control is present in both runs.
The original index remains unchanged, and no pane is launched or cycled.

Base: `c666ed268a277d57b0db63cf12b789d42cbe984d`.
Demonstrated implementation: `f48c22e` (the recording commit adds only this demo).
The recording prints the complete demonstrated candidate revision.

From the repository root, repeat:

```sh
python3 docs/demos/crew-memory/run.py
```

The script exports the base package into a disposable directory. Its only cards,
memory, tracker and HOME are synthetic fixtures. It runs the actual emitted hook
as a subprocess and inspects SessionStart JSON. It does not start Codex, call a
model, install a package or mutate a live crew workspace. Private memory contents,
paths and hashes are not part of this public demonstration.

Download both text files and replay in a terminal with util-linux:

```sh
scriptreplay --log-out recording.txt --log-timing timing.txt
```

This is a terminal recording with readable output, not an inline video or proof
of installed delivery. Account isolation, truncation, unsafe-source refusal and
tracker-UNKNOWN context are covered by the focused regression suite.
