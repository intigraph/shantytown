# Display-only roster observation

Base: `d572d8c5088afb54b0af0182c9bd9c18feb376e8`. Recorded program:
`5cc3881c622d3350f2a570236597d8571f2c249a`. Later artifact-only commits preserve
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
