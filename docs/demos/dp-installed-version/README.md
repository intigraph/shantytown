# Desire Path installed-version detector

The same native CLI fixture rejects `dp --version` and accepts `dp version`.
The base reports UNKNOWN for both 0.12.1 and 0.12.2; candidate reports false
for 0.12.1 and true for 0.12.2. A missing binary remains UNKNOWN.

Base: `2bd929f85aaedc9afcb28ebdb0c9cc73e3bae1dc`. Candidate product commit:
`801b2b0d`. This is an isolated source-library demonstration with an explicitly
synthetic CLI response, not installed orchestration acceptance.

Reproduce: `python3 -B docs/demos/dp-installed-version/demo.py`.
The actual terminal recording is [output.log](output.log), with [timing.log](timing.log).
Download both and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

The output log is also a readable transcript. These small files remain in Git.
