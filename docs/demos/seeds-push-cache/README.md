# Shared metadata window demonstration

This synthetic library probe issues twelve identical reads against counting
fixture functions. The base issues one query and thirteen watermark requests;
the candidate issues one query and two watermark requests. Advancing the clock
one second and changing the transaction returns the new value in both versions.
No live service is queried or changed.

Base: `e7fcee4ec1ee500df29126eb0660979541922111`. Candidate: the source in
this PR; the PR caption pins the demonstrated commit. The recording is retained
here alongside the reproducer, following the existing `docs/demos` convention.

Reproduce from the repository root:

```sh
git show e7fcee4ec1ee500df29126eb0660979541922111:shantytown/seeds_read_cache.py > baseline-cache.py
python3 docs/demos/seeds-push-cache/probe.py baseline-cache.py
```

Run tests and probes under the deployment's HOME/resource guard. The temporary
baseline file is a fixture, not source to commit.

The actual terminal recording is [output.log](output.log) with
[timing.log](timing.log); download both and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Replay was verified. This is a terminal recording with a readable transcript,
not an inline video. It proves source behavior under a synthetic clock, not
installed traffic reduction. The push bridge's zero-primary-request and refusal
controls are in `tests/test_seeds_push_read.py`; live push admission remains a
separate deployment step.
