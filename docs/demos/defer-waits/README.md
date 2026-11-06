# Event waits and owner reminders

The same CI-pending, one-hour date-only request is accepted on base
`00aeb887d5ec2f8575283bd1c8eca5bbf09aa795` and refused by the candidate.
An explicit scheduled `--window` remains accepted. The same expired owner timer
routes to the administrator on its third observation before, and stays with its
live owner after. These are real library calls against disposable file fixtures,
with synthetic runtime liveness and delivery; no tracker, pane or service is used.

The PR identifies the exact candidate revision; the recording commit adds only
artifacts to that reviewed behavior. [Source digests](source-sha256.json) retain
the implementation identity demonstrated by the recording.

[Recording / readable transcript](output.log) and [timing](timing.log) are small
sanitized util-linux artifacts retained here with the source. Download both and
replay with `scriptreplay --log-out output.log --log-timing timing.log`.
No inline player or installed acceptance is claimed.

To repeat, extract the base's `shantytown` directory to a private temporary
directory, then run from the candidate root:

```sh
DEFER_DEMO_BASELINE=/path/to/base python3 docs/demos/defer-waits/run.py
```

The separate acceptance gate is an installed 24-hour tend-log observation with
fewer than three administrator deferral-ruling digests. This recording does not
establish that outcome.
