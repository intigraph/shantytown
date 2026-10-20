# Scheduled inbox child: source demonstration

Baseline `708b0348d7ff5dbe140397b95f0b339a4c23a2b4` has no scheduled-inbox
module or demo (same demo command exits2: absent file). The candidate adds a
fixed durable-inbox child for the existing signed receiver. Measured module
SHA256: `b8539c91a2a091e02ac9bd55b0444501d5c1aa36f86b80ee30bc8b7e79576c22`.

Run `python3 docs/demos/scheduled-inbox.py`. Watch actual child processes persist
one attributed pointer to a temporary FilesInbox, refuse an absent recipient,
and reject a missing result channel without a second pointer. No production
service, real recipient, graph, signing key or natural schedule is involved.
The separate unit controls simulate a commit followed by a lost response and
verify no terminal receipt or retry; that simulated failure is not in the
recording. Success in the recording means persistence, not live submission or
watch completion.

Download the [output recording](scheduled-inbox.log) and
[timing](scheduled-inbox.timing), then replay with
`scriptreplay --log-out scheduled-inbox.log --log-timing scheduled-inbox.timing`.
Both files are small source artifacts retained with this change. Download and
terminal playback are required; no inline video is claimed. The exact reviewed
proposal head is supplied in the PR. Runtime admission stays separate.
