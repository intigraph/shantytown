# Landed-work cycle guard demonstration

The same real Git topology runs against base
`85fde581526af6092c423b5ec2a907891283c2e4` and the candidate identified by the PR:
create two feature commits, squash onto main, and delete the remote feature
branch. The forge metadata is an explicit synthetic fixture containing the actual
Git head and merge SHAs; no live forge or agent lifecycle calls occur.

Watch the false unpushed count change from **2 to 0**, allowing a checkpointed
cycle. Add one genuinely unpublished commit: the old count is **3**, the new
count is **1**, and both versions refuse. Candidate output names the merged-PR
head proof. This demonstrates source behavior, not a live fleet cleanup.

The small [output log](output.log) is a readable transcript. Download it with
[timing.log](timing.log) and replay using util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Reproduction uses the [fixture](demo.py), optionally taking a source directory:

```sh
python3 demo.py /path/to/base-source
python3 demo.py
```

The recording is retained with this source example. Local terminal playback was
verified; no inline web player is claimed. An immutable `git archive` extraction
of the base package supplies `BASE_SOURCE` when running `run.sh`.
