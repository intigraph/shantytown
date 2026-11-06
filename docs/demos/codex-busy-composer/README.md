# Busy composer footer

The sanitized captured Codex pane is busy, with a wrapped typed message and
`tab to queue message` instead of the shortcuts footer. Before the fix, its
composer reads `no-box`; the watcher cannot observe its input. After the fix,
the same capture reads `queued` while its run state remains `busy`. The text is
preserved. A genuinely unreadable control still returns `?` (UNKNOWN).

This is source replay, with no live typing, submission, clearing, notification
or deployment. The fixture retains the captured row layout and chrome, replacing
the private message, path and task name. Baseline:
`39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076`; candidate: the commit containing
this demo.

```sh
python3 docs/demos/codex-busy-composer/demo.py --base 39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076
```

The [terminal recording](output.txt) is also a readable transcript. The
[timing file](timing.txt) is retained beside it in Git. Replay was verified;
no inline video playback is claimed:

```sh
scriptreplay --log-out docs/demos/codex-busy-composer/output.txt --log-timing docs/demos/codex-busy-composer/timing.txt
```

The required 24-hour live alert acceptance remains separate from this fixture.
