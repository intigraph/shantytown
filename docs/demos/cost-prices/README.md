# Partial dollar display demonstration

A local Camayoc-result fixture has 100 tokens, 50 priced, and a known USD 0.5
subtotal. Watch the old source emit no currency samples, then the candidate show
UNKNOWN for the complete cost and emit the distinct known-subtotal metric.
No closure receipt is created from this pricing fixture.

Base: `bccb036cd65183cc16f79a2c56fe24419565afbe`. Candidate: this display change.
Run `python3 docs/demos/cost-prices/demo.py` from the source checkout.
No service or tracker is called; this does not prove installed acceptance.

[Actual output](output.txt) and [timing](timing.txt) are retained for replay:
`scriptreplay --log-out output.txt --log-timing timing.txt`.
