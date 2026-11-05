# Quipu write provenance: identical context before and after

The recorded library probe calls the actual `quipu_auth.write_headers` helper
with synthetic context and a fixture credential provider. It makes no HTTP call
and prints only the five provenance fields, never authentication headers.

On base `1b32b5ef706b282b6a83fdbe5f1f40d57fe1ac7c`, all five fields are absent.
On the candidate, complete context supplies all five. Incomplete agent context
still omits agent and model, preserving a visible partial result rather than
inventing identity. The candidate revision is the commit retaining this demo;
its runtime source is `69fdcbc`, the preceding transport-provenance commit.

[Recording output](output.log), [timing](timing.log), and [reproducer](probe.py).
Download both recording files and play with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was checked with `scriptreplay`. Inline playback is not assumed.
For a fresh comparison, extract the base package and run from this directory:

```sh
mkdir -p /tmp/provenance-base
git archive 1b32b5e shantytown | tar -x -C /tmp/provenance-base
BASE_SOURCE=/tmp/provenance-base CANDIDATE_SOURCE="$(git rev-parse --show-toplevel)" bash run.sh
```

This demonstrates source behavior only. It proves no deployment, natural caller
correlation or fleet provenance coverage. Keep the small sanitized recording
with this repository's existing demos for review and retention.
