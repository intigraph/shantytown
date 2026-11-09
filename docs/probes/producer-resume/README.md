# Producer-owned resume conditions

The same synthetic marker is unsupported at base
`9b08512c078632eb54406fd1d6027aeb9f800fc1` and testable in implementation
`db0a0f94b55f9474bcf424c6896505ce2f8808eb`. The actual candidate reader then
reports one quiet day as NOT_MET, 14 authoritative quiet days as MET, and an
unavailable census as UNKNOWN. This is a source-checkout fixture; it never
reads a live producer, changes an item or claims installed acceptance.

[Output](output.log) and [timing](timing.log) are the small terminal recording,
retained here with the reproducer. Playback was checked with `scriptreplay`;
no inline video player is claimed. Repeat from the repository root with the
base commit available:

```sh
python3 docs/probes/producer-resume/demo.py
scriptreplay --log-out docs/probes/producer-resume/output.log \
  --log-timing docs/probes/producer-resume/timing.log
```

Counter bindings remain disabled pending their separately reviewed producer.
The required real parking and three natural haul observations are outside this
demonstration. MET wakes reassessment; it does not close recurring work or
promote a policy.
