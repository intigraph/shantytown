# Existing-agent remote pairing demo

Run `st agent remote list --json`: base rejects the command (exit 2); candidate
reports one connected agent and one inactive agent (exit 0). The same candidate
then shows dry-run discovery, explicit manual-code issuance, and an expired
response withheld with exit 2. Every displayed code and provider identity is
synthetic. This exercises the real CLI parser and dispatch with a fixture
registry and transport; it does not connect a phone or a live daemon.

Base: `2c880419efcdd25b91dcf49c0aa6c539c8ad631d`.
Implementation: `e9983fca3b857034d187ce5661efb68a392862bf`.
Recorded 2026-10-18 with Python 3.14 and util-linux `script`; retained here as a
small repository artifact. Later demo-only commits preserve that implementation.

Download [output.log.gz](output.log.gz) and [timing.log](timing.log), then replay:

```sh
gzip -dc output.log.gz > output.log
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was verified with `scriptreplay`. A browser does not provide an inline
player for this format. The [readable transcript](transcript.txt) is the text
fallback. To reproduce from a checkout containing the implementation:

```sh
git worktree add --detach /tmp/st-remote-before 2c880419efcdd25b91dcf49c0aa6c539c8ad631d
BEFORE_SRC=/tmp/st-remote-before python3 docs/demos/agent-remote/run.py
```

The recording proves command behavior against controlled responses. Linux peer
identity and socket validation have separate tests. Android UI, QR payloads,
selected-conversation delivery, and reconnect persistence require independent
acceptance; code issuance alone does not establish them. No lifecycle action or
real credential appears in this recording.
