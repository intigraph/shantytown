# Separate durable inbox graph

The [recording archive](terminal-recording.zip) and [readable transcript](output.txt)
show the same private native Seeds fixture on base `37e714e6b83a3a6394262f5d8074ae298099d458`
and this proposal's candidate source. No installed service or production graph is changed.
The archive is retained beside its reproducer; download it for terminal replay.
Inline video playback is not claimed.

The fixture starts with one real work item on the work board and one legacy-prefix
receipt on the inbox graph, representing an already migrated pointer. With identical
configuration and input, base misses the receipt and creates a new message on the
work board. Candidate finds the old receipt, allocates new `messages-` IDs on the
inbox graph, and leaves zero inbox pointers on the work board. After marking the old
message read, the closed receipt remains discoverable. Real work stays open on both.

With native `sd` installed and `INBOX_BASELINE` pointing at that base checkout:

```sh
bash docs/demos/inbox-graph/record.sh
```

Extract `terminal.log` and `terminal.time` from the archive, then replay:

```sh
scriptreplay --log-out terminal.log --log-timing terminal.time
```

The recording uses `script --return`; both command success and playback were checked.
It demonstrates routing after migration, not the migration operation. The separate
reviewed import/selected-retirement capability, writer cutover, deployment configuration,
TTL scheduled-run acceptance and live cost/count controls remain required before activation.
