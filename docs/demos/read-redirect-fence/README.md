# Redirect fence demonstration

Run `python3 docs/demos/read-redirect-fence/demo.py` from the repository root.
The synthetic loopback fixture returns a redirect. The previous admission plus
ordinary transport dispatches two requests; the fenced transport dispatches one
and reports a local refusal. The budget-OFF control still dispatches both.

Actual transcript (source fixture, not an installed service):

```text
previous transport: completed; requests=2; paths=['/start', '/answer']
fenced transport: redirect refused locally; requests=1; paths=['/start']
budget OFF control: completed; requests=2; paths=['/start', '/answer']
```

The previous path reproduces the transport used at base `14252924`; the candidate
runs the new helper in this change. This is a readable transcript, not a video;
no terminal recorder is installed. The small reproducer and transcript remain
in this repository with its ordinary documentation retention. SDK-internal HTTP
and fleet activation are outside this demonstration.
