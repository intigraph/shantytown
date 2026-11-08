# Display-only roster observation

Base: `d0e8899ae8bf8553637e9859baae6bb4bb918338`. Recorded program:
`c70b8aa2b0f40b1ce51e680df77a9247c040f0c3`. Later artifact-only commits preserve
these program bytes. This is a replayable terminal recording, not a video.

The same new flag is refused on base. On the candidate, a missing private
registry returns UNKNOWN; an explicitly empty private registry returns a fresh
v2 display envelope with decision eligibility false. Two JSON presentations
and a count presentation share ONE actual local refresh producer. No installed
service, peer, credential, activation or production performance is demonstrated.
The output shows selected response fields to omit host/root metadata.

[Transcript](transcript.txt) · [Timing](timing.txt) · [Reproducer](run.py)

Replay after downloading both text files:

```sh
scriptreplay --log-out transcript.txt --log-timing timing.txt
```

Repeat from a source checkout (the base Git object must be available):

```sh
python3 docs/demos/display-snapshot/run.py
```

The synthetic registry and archived base are temporary. The recording and
caption use the repository's existing docs/demos retention convention.
