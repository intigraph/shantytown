# Scoped active-anchor lookup

A stop with a future-dated active anchor must resume that same anchor. The actual
base stop-hook code reads the global active list; the proposed helper uses the
backend's exact owner projection. Both select `own-parked`. A partial owner read
raises and never attempts global hydration.

Base: `f3d23bfdb2344d491f3fafb8da19f5e26ba922b6`. Head: the proposed source in
this PR, identified by its PR head SHA. Run from the repository root:

```sh
python3 docs/pr-demos/dnw-scoped-haul.py f3d23bfdb2344d491f3fafb8da19f5e26ba922b6
```

The [terminal recording](dnw-scoped-haul.typescript) is a readable typescript with normalized line endings;
the [plain transcript](dnw-scoped-haul.txt) contains the same command output.
This is a mocked backend library demonstration, not a native query-cost or fleet
measurement. Native integration controls are in `tests/test_haul_active_native.py`;
they require an explicitly supplied isolated Quipu server binary. No production
endpoint is used. Retain these small artifacts with this change.
