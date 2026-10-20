# Finite command attribution

The retained terminal recording compares the previous generic `shantytown`
source with the command-scoped `st-anchor` source over a loopback HTTP server.
`X-Quipu-Operation` stays `query`. An unrecognized argument maps to `st-other`,
and nested scopes preserve the outer command before restoring prior context.

[Recording](output.txt) · [Timing](timing.txt) · [Replay](demo.py)

```sh
python3 docs/probes/command-attribution/demo.py
```

The before source is commit `0c0820fbc89885239c8662b6c1c4041eb32f14c5`;
the after implementation is `ff649cb7ef04eb470356b40ecb9a014767dfade6`.
The recording exercises request headers and scope restoration locally. It does
not show an installed client, a deployed server, or a production traffic result.
No arguments, item identifiers, credentials, or metric labels are emitted.
