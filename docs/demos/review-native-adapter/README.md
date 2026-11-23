# Native review enqueue adapter

This replay uses an isolated controller store and real scoped Ed25519 signatures
against an RDF/recorded-verification fixture. The forge and native process are
synthetic adapters. A current signed APPROVE reaches one native enqueue call;
revoking the registered verifier then refuses without another native call.
It does not enqueue a real PR, qualify live native hold/CI gates, install keys
or enable a flag. The native process fixture returns an explicit test receipt.

Repeat from this source checkout:

```sh
PYTHONPATH=.:tests python3 -m pytest -q -s --disable-warnings \
  tests/test_review_enqueue_native.py::test_adapter_rechecks_real_scoped_signature_and_quipu_revocation
```

[Recorded output](output.txt) and [timing](timing.txt) are retained beside the
source. Download both and run
`scriptreplay --log-out output.txt --log-timing timing.txt`.
The output is also a readable transcript; no inline video is claimed.
