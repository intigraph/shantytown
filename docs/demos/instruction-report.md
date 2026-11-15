# Instruction report projection

Before: base `ea5608bcaedd7405c7815b708b576e0f4d8f65ae` returns an empty comparison with a tooling manifest configured and graph instruction config inactive. After: implementation `9ff06445440fa0a7e13d73fbb4f825b4d7514eaf` reports both instruction files, their byte hashes and unequal status.

The recording executes the same isolated CLI fixture against each source. No live crew workspace is provisioned. It confirms unchanged instruction bytes, retained AGENTS symlink and no MCP artifact. The graph query is replaced with a fixed manifest; this demonstrates composition and reporting, not production graph availability or installation.

Replay with `scriptreplay --log-timing docs/demos/instruction-report.timing --log-out docs/demos/instruction-report.output`. Fixture: [instruction-report-demo.py](instruction-report-demo.py).
