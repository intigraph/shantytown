# Duty repair records

The same synthetic orphaned duty calls the production SDK adapter at base
`6c115c7fa034d46965201f98219ef7627e5cef4b` and candidate source
`2a45a8ae45460978c33756417c23575238486c2b`. Before, it creates a default task
and leaves it open after recovery. After, it creates `ops` and closes the exact
record on verified recovery, using its revision. A foreign target refuses
without writing. The board transport is in memory; this proves source behavior,
not installed or scheduled acceptance.

Run `python3 docs/probes/pr-demos/ops-duty/demo.py` from this checkout.
Download [recording.txt](recording.txt) and [timing.txt](timing.txt), then replay:

```sh
scriptreplay --log-out recording.txt --log-timing timing.txt
```

This small sanitized recording is retained with the source. No inline player
or public upload is required.
