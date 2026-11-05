# Former-name contracts

Current tool commands use Tambo and Yupana. This is the per-path allowlist
for retained former-name mentions, including this compatibility explanation.
Scan all tracked readable files case-insensitively, with a whole-word match
for the former structural tool name. New current-product uses are not allowed.

| Path | Reason |
| --- | --- |
| `CHANGELOG.md` | Published release history retains original titles. |
| `shantytown/cli.py` | Explicit legacy checkout-topology examples explain why an old rig directory must resolve to its active source checkout, including push resolution. |
| `shantytown/guard.py` | Historical measured checkout paths retain their actual names; changing product names does not change the observed filesystem topology. |
| `shantytown/harness.py` | Explains compatibility with the pre-rename config table; the fallback must continue to read existing configs. |
| `tests/test_hook_bundles.py` | Detects both current and historical installer commands in hook bundles. |
| `tests/test_resolve_repo.py` | Reproduces legacy rig/source/worktree topology to prevent pushing the archived checkout. |
| `tests/test_roles_pre_edit.py` | Deliberate obsolete-command refusal controls; the old command must be reported unhealthy. |
| `tests/test_stats.py` | Compatibility cases prove telemetry records the executable actually run, including a legacy alias inside a timeout wrapper. |
