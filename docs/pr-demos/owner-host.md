# Host-scoped owner liveness

Replay identical fixtures against base
023868ba and source 423f2eb809276f15b20a6af55fe7e9544e4e120c.
With selected host `here`, a host-less owner's missing local pane previously
became `down` and a re-owner proposal. After the fix, both null and empty host
placement remain `unknown`, no local probe occurs, and no re-owner is proposed.
The explicit same-host/down positive control still proposes re-ownership;
foreign-host cards remain unprobed. Every result keeps `changes_applied: false`.

[Recording output](owner-host.output), [timing](owner-host.timing),
[reproducer](owner-host.py). Small sanitized artifacts are retained in the
existing demo directory. Download the recording pair to replay:

```sh
scriptreplay --log-out owner-host.output --log-timing owner-host.timing
python3 owner-host.py --source /path/to/source-checkout
```

Playback was verified with util-linux scriptreplay. No inline player is claimed.
Registry, pane liveness and tracker rows are isolated fixtures; no model,
tracker write, assignment change or live pane mutation is involved. This proves
source behavior, not installation of the changed helper.
