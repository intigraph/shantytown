# Deferral evaluation fields demo

The frozen offline fixture contains 50 deferred candidates and one dated-open candidate. Watch full fixture rows and projected candidate fields produce the same findings, with candidate order and condition notes preserved. The candidate performs four bounded reads and omits unused bodies. A failed read is UNKNOWN.

Base: `49ce946b2923a000756623f429158b3536573ecd`. Runtime candidate: `5200c4e` (identical runtime tree to tested `89b3595`). Run `PYTHONPATH=. python3 docs/probes/pr-demos/deferred-fields/reproduce.py` from the commit containing this directory. The transport is mocked and time frozen. This demonstrates projection and evaluation parity; it does not measure the base SDK request count, deployment, full-pass cost or hourly rate. Full detail and a fresh condition remain separate release barriers.

[Recording](demo.cast) is asciinema v2. Download and replay with `asciinema play demo.cast`; inline playback is not claimed. [Transcript](transcript.txt) contains the same actual output. Output timing was recorded from the subprocess. The small sanitized artifact is retained in the repository's existing PR demo directory.
