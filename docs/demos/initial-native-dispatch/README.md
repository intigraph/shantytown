# Initial dispatch consults native consumption evidence

Before: the actual terminal adapter sends once but cannot confirm an exact body
from its terminal echo; initial dispatch leaves a prepared receipt with no
submission or assignment. The native Claude user record is available to the
existing observer but the initial dispatch never asks it.

After: initial bound dispatch polls that reader for at most five seconds and
11 observations. A matching body, session and runtime permits the existing
submission transition and single assignment CAS. Queue-only records and a
replacement runtime leave the receipt pending and unauthorized.

[Recorded output](output.log) and [timing](timing.log) compare baseline
`6906320da6e0b36a27cddacccafb37a9fbb42cd1` with the repaired source. The probe
uses the actual terminal adapter, native transcript reader, dispatcher, receipt
ledger and file assignment adapter. Terminal calls and native log timing are
isolated fixtures; it never types into a live pane or calls the production board.
Installed peer acceptance remains a separate check.

With pytest installed and both source trees available:

```sh
export NATIVE_DEMO_BASELINE=/path/to/baseline-source
export NATIVE_DEMO_CANDIDATE=/path/to/repaired-source
python3 docs/demos/initial-native-dispatch/probe.py
```
