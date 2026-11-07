# Package versions and private addresses

A pinned public wheel was refused because its numeric version matched the private-address rule. The corrected guard recognizes numeric version fields only in structurally valid wheel and tar filenames. Arbitrary URL path addresses, private authorities, queries, fragments, adjacent leaks and malformed artifacts still reach the original matcher. Parser failure retains the original text.

The recorded source fixture compares base `39f4bf93a956c57a1b7a7ec7f42be3a46cb4a076` with code head `c21443fb96ad9f88696c4fe8fd9a8653bdb0f785`. The candidate guard SHA-256 is `ff070dc17bd3d16cb9391aaac3236a484aa532bf78bfed9f6c26c397a16eb011`.

The same pinned wheel fixture is refused before and allowed afterward. All 36 candidate context controls pass; address paths, private hosts, queries and named-host leaks return hook exit 1. Chained refusal remains effective. The baseline stops at its first false positive, so elapsed times are not a speed comparison.

Run `python3 docs/pr-demos/version-context/demo.py` to reproduce using disposable hook copies. It makes no network push and changes no installed hook. Download both [output.log](output.log) and [timing.log](timing.log), then replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

This source-fixture recording does not establish hosted CI, independent review or installed propagation.
