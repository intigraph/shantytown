# SDK display-read coalescing

Eight concurrent bounded-staleness SDK `list` callers previously dispatched eight
children. Watch the `stubbed_child_dispatches` field: base8 becomes candidate1
for both successful and failed cohorts. All eight successful callers still get
populated answers; all eight failing callers refuse. An exact read afterward
still dispatches one additional child on both sources.

This is a **replayable terminal recording of a source fixture**, not an installed
service or HTTP-rate measurement. The actual SDK runner is fully stubbed by
`tests/test_sd_stale_singleflight.py`; no child executable or remote store is used.

- Base: `ddfc3b53113a92b660f1528e99ee9a0332f52f50`.
- Candidate functional source: `23a0d3ffd8bd0a98ec1923e00d23c5dec21a7e89`.
- Actual `sd.py` SHA256s are printed in the recording. The later demo-only commit
  preserves that candidate runtime source.
- [Output recording and readable transcript](output.log), [timing](timing.log).
  These small sanitized artifacts are retained in this repository's existing
  `docs/demos` destination.

Download both files and replay with util-linux `scriptreplay`:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Local replay was verified. This is not an MP4 or an inline browser player.

To repeat, use a development Python with pytest installed. From the candidate
source root, export the base into a private temporary directory, then copy the
same reproducer and fully stubbed fixture to that export:

```sh
base_export=$(mktemp -d)
git archive ddfc3b53113a92b660f1528e99ee9a0332f52f50 | tar -x -C "$base_export"
mkdir -p "$base_export/docs/demos/sdk-display-coalescing"
cp docs/demos/sdk-display-coalescing/demo.py "$base_export/docs/demos/sdk-display-coalescing/"
cp tests/test_sd_stale_singleflight.py "$base_export/tests/"
DEMO_BASE_ROOT="$base_export" bash docs/demos/sdk-display-coalescing/record.sh
```

Remove the disposable export afterward. The native owner-display regression is
separately covered by `tests/test_owner_display_singleflight.py`: a cold cohort
of eight readers falls from16 candidate/field requests to2. Neither fixture
establishes live80% reduction, host-wide HTTP budget coverage or recycle health.
