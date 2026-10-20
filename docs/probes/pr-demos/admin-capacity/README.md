# Administrator capacity inside the account cap

The same private two-host fixture starts with two workers at cap 3 and an
offline canonical administrator. Before, another worker takes the last slot
and administrator repair refuses at 4/3. After, the worker is refused because
that slot is reserved; administrator repair is admitted within 3/3.
`--despite-hold` is true in both sequences and does not change the account cap.

Base: `c90765e89ea116f5b2aab234e3794031412ba107`. Candidate implementation: `60112a24e9d03ea379a55f97c5b6600c25052733`. The recording exercises
source through the CLI admission helper with mocked peer/process observations
and private registry files. It starts no session and proves no deployment.

From the repository root run `python3 docs/probes/pr-demos/admin-capacity/record.py`.
Download [output.log](output.log) and [timing.log](timing.log), then replay with
`scriptreplay --log-out output.log --log-timing timing.log`. A readable transcript
is the output log itself. Playback requires util-linux; no inline player is
provided. These small sanitized source-fixture artifacts are retained with this
proposal in the existing demo directory.
