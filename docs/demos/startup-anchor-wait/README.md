# Startup-anchor delivery wait

Trigger: a Codex ephemeral pane still runs startup-anchor hooks with an empty
composer, then becomes idle. Base `e0a982d8fb74fafe870e2c6ad88c3b6d54b41188`
attempts delivery immediately and fails; candidate CLI source blob
`b14945f79bdac2824fbb1ea086f41f77b9a75ebb` observes busy/busy/idle and delivers
once. Foreign composer and persistent busy controls refuse without typing.

This is a recorded source API probe with synthetic pane frames and job records.
The pane's send receipt is a fixture; no actual Codex process or live job starts.
Time sleeps are disabled to show the bounded 121-observation timeout quickly;
production also enforces a monotonic 60-second deadline. It demonstrates waiting,
not installed launch reliability or model selection.

Repeat from repository root: `sh docs/demos/startup-anchor-wait/demo.sh`.
Download `output.log` and `timing.log`, then replay with:
`scriptreplay --log-out output.log --log-timing timing.log`.
The recording and caption are retained with the source. Playback was verified
locally; no inline video player is claimed.
