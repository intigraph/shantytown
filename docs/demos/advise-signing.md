# Signing profile observation demo

The same explicit actor inputs reach the real Seeds adapter on base
`15ddda519e481f70277ce94c0dad826c907d17b4` and source revision
`6b47777f3e0f99fe5a811c7054fe00bf5c1b9dd0`. The identity and mutation transport
are synthetic: this demonstrates child selection and observation, not signature
verification, trust enrollment or an installed deployment.

The same reproducer was rerun on
`79fa82147eac70fc5ddffd49a343f41ddc29a421`, which adds malformed-profile fallback;
both demonstrated outputs were unchanged and the guarded command succeeded.

Before: both writes use the legacy child environment, with no per-write
principal receipt. After: each mutation selects the profile only for its child;
a matching actor records `match: true`, and an explicit different actor records
`match: false`. Both mutations execute once and return success. The fixture
creates no signing keys and contacts no service.

[Readable transcript](advise-signing.txt), [original output](advise-signing.log.gz) and [timing data](advise-signing.timing)
are retained here as a small terminal recording. Replay was checked with:

```sh
gzip -dc docs/demos/advise-signing.log.gz > /tmp/signing-demo.log
scriptreplay --log-out /tmp/signing-demo.log --log-timing docs/demos/advise-signing.timing
```

This requires a terminal replay tool; no browser embed is assumed. To reproduce
the same adapter comparison from the candidate checkout:

```sh
mkdir -p /tmp/signing-demo-base
git archive 15ddda519e481f70277ce94c0dad826c907d17b4 shantytown | tar -x -C /tmp/signing-demo-base
python3 docs/demos/advise-signing.py --source /tmp/signing-demo-base --label base
python3 docs/demos/advise-signing.py --source . --label candidate
```

The script patches only the optional policy location, policy owner, original
child environment and subprocess transport. It invokes the actual `_bd_in`
adapter and reads the actual appended observation. A production acceptance
still needs enrolled keys, normal writer coverage and actual write read-back.
