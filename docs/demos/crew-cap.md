# Ten-item assignment cap

The same isolated complete owner plate receives one new P0 request on base
`7510e04d678235a4b3b56bdf7faa907cf49feb1c` and this candidate. Both admit a
tenth item. Only the base admits an eleventh; the candidate refuses it.
The recording exercises the source library, without backend writes or dispatch.
It does not demonstrate installed behavior or cross-host atomic enforcement.

[Terminal recording](crew-cap.cast) (download and replay with
`asciinema play crew-cap.cast`). The recording is retained with this change.
Its frames preserve the actual output and timing from an output-only terminal
capture; inline playback is not claimed.

Reproduce from this checkout, retaining the base commit locally:

```sh
PYTHONPATH=. python3 docs/demos/crew-cap.py
```

Expected output:

```text
BASE 7510e04d: held=9/10 new=P0 -> ADMITTED
BASE 7510e04d: held=10/10 new=P0 -> ADMITTED
CANDIDATE hard-ten: held=9/10 new=P0 -> ADMITTED
CANDIDATE hard-ten: held=10/10 new=P0 -> REFUSED
```
