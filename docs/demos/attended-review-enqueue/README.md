# Attended approval to enqueue

Before: the attended report wrote its signed verdict and ended without calling
enqueue. At baseline `05a0418784878af1a26d2cdb405a8ee1f970bfc1`, the attended
CLI regression reports approval and tears down, but its adapter-call assertion
fails because no call occurred. That baseline probe omits the new launch-head
assertion so it can reach the old report behavior.

After: two cryptographically verified attended approvals for the same job and
head, with different signature timestamps, invoke the Action once.
A lost reply remains UNKNOWN after a later signed approval and does not retry.

[Compressed output](output.log.gz) and [timing](timing.txt) record the production custody code
with private signed RDF fixtures and a stub Action. Replay with util-linux:

```sh
gzip -dc output.log.gz > output.log
scriptreplay --log-out output.log --log-timing timing.txt
```

The CLI regression separately exercises launch-head binding, report, configured
adapter subprocess and detached teardown. These offline tests do not launch a
real crew job, enqueue a real PR or establish protected-UID runtime readiness.
The flag remains off; live forge acceptance and operator policy admission are
separate gates.
