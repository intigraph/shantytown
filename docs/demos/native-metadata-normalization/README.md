# Metadata normalization under the refresh lease

A real local Git/FD fixture holds the exclusive source lease, changes only the
two reviewed metadata modes to 0755/0644 and measures the closure. Config bytes
and the operator pin remain unchanged. A consumer refuses until the fixture
operator explicitly replaces and reads back its pin; it then qualifies.

Repeat: `python3 -m pytest -q -s tests/test_native_source_pin.py::test_reviewed_refresh_normalizes_only_metadata_and_returns_unadopted_proof`.
[Output](output.txt) and [timing](timing.txt) are retained for download and
`scriptreplay --log-out output.txt --log-timing timing.txt`.

This fixture models protected pin installation. No live metadata, ACL, pin,
refresh, runtime flag or job is changed; initial provisioning/adoption is separate.
