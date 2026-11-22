# Job tools and context

Output-only recording of an isolated workspace on base `b4d5a1fa` and the
candidate containing this artifact. The same synthetic kit contains search
and mail MCP servers. The candidate's explicit JobSpec keeps search only,
disables Claude account connectors and refuses a missing selected server.
A simulated graph timeout remains UNKNOWN; no remote service is contacted.
This demonstrates library/provisioning boundaries, not a live job launch.

From the repository root:

```sh
python3 docs/probes/pr-demos/job-tool-context/demo.py
scriptreplay --log-out docs/probes/pr-demos/job-tool-context/output.log --log-timing docs/probes/pr-demos/job-tool-context/timing.log
```

The small recording and timing file follow the existing directory's retention
convention. Download both to replay; inline playback is not assumed.
