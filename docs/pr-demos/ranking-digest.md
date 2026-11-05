# Compact ranking digest

The same isolated five-worker/34-READY fixture is replayed against base
42700874c0ef2207b54caaea619ff9bd5e8f7096 and source
20a7ed8466e376e747b5c8bdc124d2572bf77fa8.

Before: 2,338 UTF-8 bytes, the 34 IDs repeated for each worker, and six copies
logged in six simulated ten-minute sweeps. After: 384 bytes, one comparison per
worker, one priority/rank-sorted top-five list plus `+29 more`, and one digest
logged in those six sweeps. At the hourly boundary the reminder logs again.
P1 mismatches produce zero administrator pushes in both versions.

[Recording output](ranking-digest.output), [timing](ranking-digest.timing),
[reproducer](ranking-digest.py). These small sanitized artifacts are retained
in the existing demo directory. Download both recording files to replay:

```sh
scriptreplay --log-out ranking-digest.output --log-timing ranking-digest.timing
python3 ranking-digest.py --source /path/to/source-checkout
```

Playback was verified using util-linux scriptreplay. No inline player is
claimed. The clock, tracker rows, live-worker set and notification sink are
synthetic; this is source behavior, not a natural installed tend run or an
observed administrator inbox rate. No actual notification or assignment occurs.
