# Repository-scoped overlap and bounded cache reads

Source-library demonstration of the same inputs before and after the repair.
Distinct explicit repositories with `src/main.py` used to score 0.9, encouraging
KEEP. The repair scores them 0.2; the same-repository control remains 0.9.
An 8 MiB final JSONL record previously required 8,388,609 physical read bytes
before the logical budget check. It now reads at most 2,097,152 bytes and
preserves UNKNOWN for that incomplete record.

Before: `df023d8438a96f4a39f78a5ccd3a70c102281e8d`.
After: `02421b40e5459e9caf1df38a8b79939c433c4434`, including the source repair
`f795e08b` and a clean main refresh. Later documentation-only commits do not
change these demonstrated functions. This measures source, not installation,
live cache eviction or calibrated task similarity.

Run from the repository root:

```sh
python3 docs/demos/cache-bounds/demo.py
scriptreplay --log-out docs/demos/cache-bounds/output.log \
  --log-timing docs/demos/cache-bounds/timing.log
```

[Output transcript](output.log), [replay timing](timing.log), and
[repeatable source probe](demo.py) are retained as small repository artifacts.
Playback uses `scriptreplay`; no inline video playback is claimed. The probe
loads the immutable before module from Git and the current checkout after module;
the transcript prints both exact revisions and actual observed results.
