# Native source pin

A real local Git/descriptor fixture qualifies its complete source closure,
blocks the refresher while a consumer holds the shared lease, then refuses a
same-size/same-mtime code mutation. The fixture models root-owned pin installation;
it creates no real operator pin, owner change, source refresh, queue mutation
or runtime activation. The bytecode-poison and child-FD lifetime controls are
separate tests in `tests/test_native_source_pin.py`.

Repeat from this source checkout:

```sh
PYTHONPATH=.:tests python3 -m pytest -q -s --disable-warnings \
  tests/test_native_source_pin.py::test_source_pin_demo_current_mutated_and_refresh_controls
```

[Output recording](output.txt) and [timing](timing.txt) are retained beside the
source. Download and replay with
`scriptreplay --log-out output.txt --log-timing timing.txt`.
The output is also a readable transcript; no inline video is claimed.
