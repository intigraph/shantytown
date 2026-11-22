# Explicit Ask type stays off crew queues

The same synthetic rows are evaluated by the base and candidate packages. An
Ask with an ordinary title and no legacy decision labels used to count as
worker capacity and enter the worker's haul. The candidate recognizes its
explicit type and keeps only the ordinary work in those queues.

[Recording](output.typescript), [timing](timing.txt), and
[readable transcript](output.txt) are retained with this source for review.
Replay with `scriptreplay --log-out output.typescript --log-timing timing.txt`.
Reproduce with `DEMO_BEFORE=/path/to/base DEMO_AFTER=/path/to/head python3 demo.py`.
The roots must contain the corresponding `shantytown` package.

Base: `e7f9b54064d4abcc5eb51bdc00f853d0a7311ee5`; candidate: this PR's source.
This uses actual library functions on source fixtures, with no live board,
credentials, dispatch or installed acceptance. Native SPARQL count behavior and
exact metadata projection are covered separately by regression tests.
