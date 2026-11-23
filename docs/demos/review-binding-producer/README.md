# Automatic review binding producer

Two isolated controller fixtures use real scoped signatures and RDF recorded
verification. With the approval still current, the producer makes one synthetic
native classification and one synthetic enqueue. Revoking the verifier after
classification refuses the enqueue. Classification artifacts and attempt claims
are private fixture files; forge/process effects are synthetic, not live native
or production acceptance. No flag, key enrollment or real queue changes.

Repeat from this source checkout:

```sh
PYTHONPATH=.:tests python3 -m pytest -q -s --disable-warnings \
  tests/test_review_enqueue_bindings.py::test_real_scoped_approval_is_checked_again_after_native_preparation
```

[Output recording](output.txt) and [timing](timing.txt) are retained beside the
source. Download and replay with
`scriptreplay --log-out output.txt --log-timing timing.txt`.
The output is also a readable transcript; no inline video is claimed.
