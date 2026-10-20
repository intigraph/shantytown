# Work-rank plate selection

The same mocked tracker rows select `old` on source `281100288e7a` and `ranked`
on candidate source `08eee231d7d6`. Adding a priority-0 item selects `urgent`
on both. This demonstrates rank within priority, with the priority control
preserved. The tracker process is mocked; no board or session is changed.

Download [output.log](output.log) and [timing.log](timing.log), then replay:

```bash
scriptreplay --log-out output.log --log-timing timing.log
```

This is a replayable terminal recording with a readable transcript, not a video
or deployment proof. Set `RANK_BASE_SOURCE` and `RANK_HEAD_SOURCE` to the two
source checkouts and run `python3 demo.py` to reproduce. The code revisions
above identify the demonstrated implementation; the later recording commit
changes documentation only. Small output/timing artifacts are retained here.

The current comparison key orders aware timestamp instants using integer seconds
and nanoseconds, including nonzero UTC offsets. Original timestamp spelling is
preserved in advisory output. Equivalent instants fall through to the existing
ID tiebreak; malformed or unzoned supplied timestamps remain uncertain. The
recording above predates this correction. Offset, fractional-second and exact
nanosecond regression controls are in `tests/test_work_rank.py`.
