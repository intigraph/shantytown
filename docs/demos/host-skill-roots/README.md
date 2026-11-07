# Host-local skill source roots

The same portable 27-skill manifest resolves zero available sources on base
`3e5aa09852c051444384b44399b44fd2449beff1` and all 27 on runtime
`ccc2cd2bcdb8592f2fe3e5b49c271a255cb09e99`. The fixture also proves byte-identical legacy-host
source projection and detects a missing local `SKILL.md`.

This records a library probe against isolated source trees, not host installation.
The provisioning tests additionally exercise both host roots through real provision
and verify unchanged MCP, instruction and source-receipt bytes. Live graph changes
and actual host acceptance remain separate.

Reproduce: `PYTHONPATH=. python3 docs/demos/host-skill-roots/probe.py`.

[Transcript](transcript.txt), [raw recording](output.log), [timing](timing.log).
Play the recording with `scriptreplay --log-out
docs/demos/host-skill-roots/output.log --log-timing
docs/demos/host-skill-roots/timing.log`. Raw bytes are preserved as plain text; the
transcript only normalizes CRLF. The fixture's temporary-path digest varies per run.
