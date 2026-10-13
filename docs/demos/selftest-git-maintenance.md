# Disposable selftests do not launch Git maintenance

A native Git Trace2 probe runs the normal scrub selftest and its sixth-init
failure control in disposable repositories. Git 2.53.0 recorded 52 maintenance
child starts before the change and zero afterward. The normal case retains all
40 functional controls; the fault is observed, exits unsuccessfully, and leaves
caller bytes and mtimes unchanged. The reported intermittent CI lock race did
not reproduce locally; the probe measures the actual maintenance launches.

The caller fixture disables maintenance before its initial commit. The guard
then runs without those caller overrides, proving its own selftest settings.
Local bare receivers also disable auto-maintenance because receive-pack drops
command-scope configuration. The ordinary push path is unchanged.

`python3 -m unittest discover -s tests -p test_scrub_guard_selftest.py` verifies
the Trace2 positive control, zero maintenance starts, all setup-failure
containment cases, and normal behavior. No real repository configuration,
maintenance lock, or process is changed by the test.
