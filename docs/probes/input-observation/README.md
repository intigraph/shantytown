# Composer observation evidence

The read-only wrapper adds bounded reasons, observation time, duration, package
version and classifier digest without retaining composer or exception text.
The conservative classifier is unchanged.

The wrapper opts into checked native capture. A nonzero capture exit becomes
UNKNOWN with `capture-failed` and no busy verdict. A successful empty/no-frame
capture remains `no-box`; timeout remains UNKNOWN with `capture-timeout`. The
adapter's default capture behavior for existing delivery and lifecycle callers
is unchanged.

## Native adapter before and after

The same probe calls the real Tmux adapter with only its subprocess result
mocked. Reviewed baseline `816a8ae833208781ba5ffbb33da3c5c3e24e4ad4` incorrectly
reports both rc0 and rc1 as successful no-frame observations. It must fail the
probe's UNKNOWN assertion. The introducing repair commit distinguishes them
while preserving successful no-frame and timeout controls. An import/build
failure does not count as the expected baseline behavior failure.

Create an isolated package fixture and run from the candidate repository:

```sh
mkdir -p /path/to/isolated-baseline
git archive 816a8ae833208781ba5ffbb33da3c5c3e24e4ad4 shantytown |
  tar -x -C /path/to/isolated-baseline
PYTHONPATH=. python3 docs/probes/input-observation/demo.py \
  --baseline-dir /path/to/isolated-baseline
```

[Real output](output.txt) and [timing](timing.txt) are a small output-only terminal
recording retained beside this caption. Download both and replay with
`scriptreplay --log-out output.txt --log-timing timing.txt`; playback was checked.
No inline player is claimed. The PR body names the exact candidate head; the
recorded adapter/wrapper bytes match that commit.

These are isolated source-library observations, not deployed state, a diagnosis
of the historical incident or original scheduled acceptance. No live terminal,
keystroke, send, clear or lifecycle operation is performed.
