# Ready-cohort field-budget demo

A synthetic queue of 1,100 items carries 13 scheduling fields each. On base `4ac66122cb6ab7c9a2233b1f07150303d1645c87`, the first field reply reaches 10,000 rows and the reader correctly refuses completeness. The candidate returns all 1,100 items across five smaller replies. Empty input remains a complete zero; a truncated reply remains UNKNOWN in both versions.

This calls the real `owner_rows` and `_project_fields` library against an isolated wire fixture. It makes no network requests, dispatches or tracker writes. Candidate `shantytown/seeds_plate.py` SHA256: `b2f21582cd65e982a1620edb3bc51bec073bcbd6ad9d2066f923a854853de545`. The PR records its exact source head. It does not demonstrate installation or a natural refill tick.

Replay the retained terminal recording (requires util-linux):

```sh
scriptreplay --log-out docs/demos/refill-field-budget/output.log --log-timing docs/demos/refill-field-budget/timing.log
```

Repeat the candidate with `python3 docs/demos/refill-field-budget/probe.py .`. To compare, check out the exact base in a separate directory and pass that directory as the probe argument. Read [the transcript](output.log) if terminal replay is unavailable. This small recording is retained with the repository; only command metadata was omitted, not the observed output or timing.
