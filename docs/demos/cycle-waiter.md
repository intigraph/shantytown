A detached waiter inherited a repository-parent working directory. In an editable
installation, its bare `shantytown` directory shadowed the installed package:
the parser failed importing `__version__`. The same parser probe using the
corrected spawn settings returns zero and exposes `--root`.

This recording uses the candidate's regression fixture (a synthetic editable
finder and namespace shadow), based on commit
`2ff8a6115a9c61f33b404a14d258fe962b2c28ee`. It calls the actual spawn function,
then substitutes `--help` for the lifecycle arguments. No cycle is performed;
installed adoption and a naturally served pending request remain separate checks.
The missing-interpreter/pending-request control is covered by the test suite.

Repeat: `python3 docs/demos/cycle-waiter.py` (requires the test dependencies).

Download [output](cycle-waiter.output.log) and [timing](cycle-waiter.timing.log),
then replay with `scriptreplay --log-out cycle-waiter.output.log --log-timing
cycle-waiter.timing.log`. The output file is also a readable transcript. This small
recording is retained in the repository's existing demos directory; inline video
playback is not claimed.
