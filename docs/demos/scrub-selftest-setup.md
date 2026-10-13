A failed fixture clone used to let the scrub-guard selftest run Git commands in
its invoking repository. The same first-clone failure changed 12 paths in a
disposable caller before this fix and zero afterwards. Both runs exit nonzero;
exit status alone did not detect the escape. The ordinary selftest still passes
40 controls and leaves the caller unchanged.

Repeat the contained demonstration with `python3 docs/demos/scrub-selftest-setup.py`.
It uses local disposable repositories, isolated HOME and Git configuration,
and no external remote. Caller snapshots compare bytes and modification times.
The regression suite injects failures at all six allocations and initializations,
three clones and five fixture directory changes, including empty failed
allocations. Fault markers prove each requested failure was actually reached.

The [recording](scrub-selftest-setup.log) and [timing](scrub-selftest-setup.timing)
retain the actual before/after calls. Replay downloaded files with
`scriptreplay --log-out scrub-selftest-setup.log --log-timing scrub-selftest-setup.timing`.
This measures source behavior; installed hook adoption requires a separate check.
