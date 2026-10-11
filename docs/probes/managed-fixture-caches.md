
## Owned test-repository census

The sanctioned fixture harness creates private `suite-XXXXXXXX` directories
under the dedicated metric-fixture pool. Public remotes created only for tests
must not raise and lower the estate's repository count when their suite exits.
The installer reports these checkouts separately as
`scrub_guard_fixture_excluded_total`; it retains ordinary coverage and the
existing shrinking-coverage alert unchanged.

The boundary requires a physical path inside that exact pool, an eight-character
suite suffix, current ownership, mode0700, a Git common directory inside the
same suite, and the effective physical Git hook directory inside that suite.
Absolute and relative core.hooksPath overrides and hook-directory symlinks are
resolved; missing or escaped effective directories stay in ordinary coverage. Unknown custody, lookalikes, symlink escapes and worktrees sharing
hooks with an external repository remain in coverage. This is a disposable
fixture namespace contract, not a general cache or temporary-directory skip.
Existing dependency-cache exclusions remain independently reported. Fixture
exclusion counts checkouts; public coverage still deduplicates real repositories
by their Git common directory.

Selftests create an owned public fixture and an ordinary public repository,
including an external shared worktree and escape controls. The scoped metric
must report one fixture separately and one real repository in coverage.
Disabling the actual fixture branch must fail the scoped reporting control.
Publication is source-only: independent review, complete CI, normal helper and
propagation plus an observed scheduled sweep are required before live acceptance.
No manual sweep, live gauge rewrite, silence or alert clear is part of this change.
