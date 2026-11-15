# CLI knowledge witness merge demonstration

Before, two disjoint CLI changes edited one committed whole-file digest, so
merging either source change into the other required a registry conflict cure.
After, the same private source edits merge in both orders to identical bytes;
the actual renderer emits their exact SHA-256 without editing the registry or
its stable summary anchor. A real summary disagreement remains a conflict, and
missing or tampered summary witnesses still refuse.

Run `python3 docs/demos/cli-knowledge-witness/probe.py` from the repository.
Replay the [recording](output.log) using [timing](timing.log):

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This uses private source fixtures and an explicit index-label fixture. It does
not prove real index coverage, installed publication or existing PR adoption.
Old branches still editing the removed fields may need one migration cure.
