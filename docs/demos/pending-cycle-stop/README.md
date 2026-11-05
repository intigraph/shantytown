# Pending self-cycle Stop boundary

A saved self-cycle request plus hard context previously produced another blocking
hint. The same fixture now allows the stop quietly. With no cycle request, both
revisions retain the hard-context block.

Recorded against base `00aeb88` and implementation `4ca282c`, using the actual
Stop-advice function and isolated configuration, transcript and request files.
No live session was cycled; busy-pane, background-task and loss guards were not
bypassed. This does not establish installed acceptance.

Read [the actual transcript](output.log), or download it with [timing.log](timing.log)
and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Repeat from the repository root:

```sh
python3 docs/demos/pending-cycle-stop/demo.py 00aeb88 4ca282c
```

The small recording and reproducer remain in this repository's existing demo
directory so reviewers need no external artifact service. No inline video
playback is claimed.
