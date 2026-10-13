# Wheel checksum demonstration

Baseline source: 569d9521739d320653fd17aaaae887ed6571f4da.
Demonstrated producer: cab12a0. Input: the unchanged published v0.4.0 wheel and
source archive, copied into a disposable directory. No release mutation or
host installation occurs in this demonstration.

Watch the missing manifest fail, the actual producer create one matching pair,
and the checksum command pass. Appending bytes to the same wheel then fails
while the unchanged source archive still passes.

With the two original release assets in a directory, run from the repository:

    RELEASE_ASSETS=/path/to/downloaded-assets sh docs/demos/wheel-checksums/run.sh

[Recorded output](output.log) and [timing](timing.log) are retained in Git.
Download both and replay with util-linux:

    scriptreplay --log-out output.log --log-timing timing.log

The output is also readable as a transcript. Raw terminal CRLF is retained.
Later documentation commits preserve the demonstrated producer behavior.
Private generation does not prove that a checksum asset has been published.
