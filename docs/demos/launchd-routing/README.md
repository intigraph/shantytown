# Launchd routing and peer diagnostics demo

Trigger: install a LaunchAgent with `seeds` declared in deployment configuration
while the installing shell says `files`, then receive a mocked SSH255 with
“No route to host” on its final stderr line. The before result omits the backend
and cause; the candidate preserves both. PATH/root and unavailable-peer controls
remain true. No SSH, launchctl, tracker request, or Mac installation occurs.

Base: `83c8ab151925d81a670463da60982b3f76187f64`. Candidate: the proposal content
in this directory's containing commit (the PR identifies its exact head).

Reproduce from the repository root:

```sh
python3 docs/demos/launchd-routing/probe.py 83c8ab151925d81a670463da60982b3f76187f64
```

The small output-only terminal recording is retained in this repository's demo
artifacts: [output](output.log), [timing](timing.log), and the
[readable JSON result](result.json). Download both recording files to replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Replay was checked locally; no inline video player is claimed. These fixtures
prove source behavior, not the environment or networking of a running Mac.
Unknown SSH diagnostics remain omitted to avoid exposing arbitrary remote stderr.
