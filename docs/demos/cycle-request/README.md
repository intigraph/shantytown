# One checkpoint post per cycle request

An explicit checkpoint file used to be posted and then followed by another
plate/comments read solely to choose text for inferred quality advice. The
candidate gives that advice the supplied file and the exact local launch stamp.
The executor still reads durable custody before performing the cycle.

The recording compares base `bccb036` with this change in an isolated request
fixture. Watch `quality_tracker_reads` change from 1 to 0, and
`quality_uses_supplied_file` from false to true. Both still post once and record
a request. The fixture stubs tracker transport, advice and the detached waiter;
it does not clear a pane or claim a live latency improvement.

- [Output transcript](output.log)
- [Replay timing](timing.log)
- [Reproducer](demo.py)

```sh
python3 docs/demos/cycle-request/demo.py
scriptreplay --log-out docs/demos/cycle-request/output.log --log-timing docs/demos/cycle-request/timing.log
```

Replay requires downloading both small log files and util-linux `scriptreplay`;
inline playback is not assumed. The logs are retained beside the reproducer as
small review evidence. No credentials or live deployment data are included.
