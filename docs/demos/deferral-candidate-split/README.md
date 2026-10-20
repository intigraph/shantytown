# Split deferral candidate fixture

Run `python3 docs/demos/deferral-candidate-split/run-demo.py` from a checkout
containing baseline commit `8f1d426bf91dd392937d00620739ff24069d634f`.
The fixture rejects multi-arm candidate queries and supplies identical duplicate
candidate identities to the separate branches. It proves the previous UNKNOWN
and the candidate's complete, deduplicated result without calling a service.

Replay `output.log` and `timing.log` with `scriptreplay --log-out output.log
--log-timing timing.log`. The transcript is also readable directly.

This deliberately increases candidate HTTP requests from one to six (ordinary
reads) or sixteen (expanded backstop reads), while preserving one total candidate
deadline and the cumulative row budget. It does not measure production latency,
total query cost, snapshot isolation, or installed scheduled-sweep acceptance.
Every branch must complete before hydration; errors remain UNKNOWN. The private
RDF fixture tests compare the split result with the original UNION across both
graphs and all candidate classes, including negative controls.
