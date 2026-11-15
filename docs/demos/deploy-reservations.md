# Deploy reservations survive crew stops

An operator-stopped owner previously made an assigned deploy reservation
eligible for the ordinary work release sweep. The same synthetic open P0
fixture now stays protected; ordinary work remains eligible.

Base: `6bccc8d7f1f502e12daba586d8fb6e47002924b4`. The recorded candidate uses
`eligible` from this commit. No tracker or fleet process was contacted.

[Terminal recording](deploy-reservations.log), [timing](deploy-reservations.timing)
and [reproducer](deploy-reservations.py) are retained here as small review
artifacts. Download both recording files to replay:

```sh
scriptreplay --log-out deploy-reservations.log --log-timing deploy-reservations.timing
PYTHONPATH=. python3 docs/demos/deploy-reservations.py
```

This demonstrates source eligibility, not installed acceptance or a natural
scheduled sweep. The composed sweep tests cover the release path and census.
