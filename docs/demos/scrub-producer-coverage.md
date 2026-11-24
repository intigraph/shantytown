# Producer scratch coverage recording

A private `produce-XXXXXXXX/source` checkout is created, armed, then removed.
Watch the persistent count: base reports **2 -> 1**, while the candidate reports
**1 -> 1**. Removing the real repository still reports **1 -> 0** on both.
Missing-guard count remains zero for these armed fixtures.

This is a source-only isolated fixture, not installed service acceptance.
Base: `05a0418784878af1a26d2cdb405a8ee1f970bfc1`.
Demonstrated behavior revision: `854351de2eae799642490989b08b56ee1b5e9189`. The recording and caption
are retained in this directory with the source; subsequent documentation changes
leave the demonstrated implementation unchanged.

Download [output](scrub-producer-coverage.output) and
[timing](scrub-producer-coverage.timing), then replay using util-linux:

```sh
scriptreplay --log-out scrub-producer-coverage.output --log-timing scrub-producer-coverage.timing
```

The output file is also the readable transcript. Playback requires downloading
these two files and a terminal; no inline player is claimed.

Reproduce from the repository root:

```sh
git show 05a0418784878af1a26d2cdb405a8ee1f970bfc1:scripts/install-scrub-guard.sh > scripts/.demo-base-install.sh
python3 docs/demos/scrub-producer-coverage.py --base-script scripts/.demo-base-install.sh --head-script scripts/install-scrub-guard.sh
rm scripts/.demo-base-install.sh
```

The full custody tests also cover missing hooks, non-private roots, lookalikes,
symlink escapes, external hooks and shared worktrees for both producer layouts.
