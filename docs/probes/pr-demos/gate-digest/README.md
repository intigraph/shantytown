## Gate-backstop delivery before and after

The same 24-chain fixture emits 12 events per pass. Before, these cause 12 admin turns; after, they arrive in one digest. A recent explicitly attributed verdict suppresses its chain during the cooldown. This recording uses private temporary fixtures, with no live item or admin delivery.

Run `./docs/probes/pr-demos/gate-digest/record.sh` to reproduce. For recorded playback, decompress `output.log.gz` and use `scriptreplay --log-timing timing.log --log-out <decompressed-output>`. Installed natural acceptance remains separate.
