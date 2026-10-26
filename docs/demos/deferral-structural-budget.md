# Deferral projection structural budget

A 25-candidate projection can exceed the server structural budget. The same
synthetic fixture goes from an incomplete observation and zero evaluated
candidates to 25 evaluated candidates: the reader first receives the explicit
structural refusal, then reads batches of 12 and 13. The server limit stays 4096.

[Recorded transcript](deferral-structural-budget.transcript.txt) and
[terminal timing](deferral-structural-budget.timing.txt) were captured with
util-linux `script` under the HOME/resource guard. Replay from this directory:

```sh
scriptreplay --log-timing deferral-structural-budget.timing.txt --log-out deferral-structural-budget.transcript.txt
```

Reproduce the production reader and sweeper fixture with:

```sh
python -m pytest tests/test_deferred_projection.py -k structural
```

The recording compares the unchanged base reader with the repaired source using
private candidate rows and a private release callback. It performs no live
lifecycle writes. Separate read-only native checks recovered the same 25 live
candidates after the identical 700-arm query was refused; those checks are not an
installed or scheduled acceptance claim.

Only the explicit structural-cost HTTP 400 triggers splitting. A singleton
refusal, exhausted time budget, or any other read failure leaves the observation
UNKNOWN; partial results never authorize release.
