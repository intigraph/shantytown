# Missing store versus an empty registry

The actual CLI runs from `/` with an isolated HOME and no root environment or
pointer. Base `f909de3e3ba445946545dd673f94edea1de2d0fd` reports exit 0 and
zero items without a store; implementation `c2e9919e` reports exit 2 and
`store_error: "no store found"`. Explicitly selecting a real empty store makes
the probe pass at both revisions. No live store, exporter or installed CLI changes.

Run `python3 docs/demos/hooks-no-store/demo.py`. The source archives are isolated
temporary fixtures. Follow-up recording commits do not change the demonstrated
implementation. The retained [output](output.log) and [timing](timing.log) can
be downloaded and replayed with
`scriptreplay --log-out output.log --log-timing timing.log`; output is also a
readable transcript. Playback requires a terminal, not an inline video player.
