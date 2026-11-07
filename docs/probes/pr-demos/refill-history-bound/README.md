# Receipt traversal past a large unrelated event

An isolated deployment fixture contains a tool-output record larger than 2 MiB
before the exact accepted native receipt at physical line 3. Base
`44b46a28ed6a49cab4a8406b8b372625e2c60862` refuses traversal; candidate source
`8cb9bd24` qualifies the same receipt. A changed target hash still refuses.
All deployment fixture bytes remain unchanged. This proves source behavior,
not installed acceptance or delivery of a new message.

[Recorded output](output.log) and [timing](timing.log) are retained here with
the reproducer, following the repository's small terminal-demo convention.
Download both logs and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Replay was checked locally; no inline player is claimed. The readable output
log is also the transcript. Reproduce from a checkout with pytest installed:

```sh
python3 docs/probes/pr-demos/refill-history-bound/reproduce.py
```

The final documentation/recording commit does not change the demonstrated code.
