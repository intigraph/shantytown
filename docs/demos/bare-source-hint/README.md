# Bare-name source refusal

The same bare repository name and explicit topic are invoked from an extra
linked worktree. Before, the refusal only suggests changing the canonical
checkout or selecting its branch. After, it also prints the literal-path form
for the current extra checkout. Both revisions refuse the original request;
the explicit-path positive control publishes the exact topic to two local bare
peers and leaves their main refs unchanged. No external Git protocol is enabled.

Base: `8f1d426bf91dd392937d00620739ff24069d634f`. Candidate: the accompanying
`shantytown/cli.py` change; the PR identifies the committed revision.

[Terminal recording](output.log), [timing](timing.log).
Replay with `scriptreplay --log-out output.log --log-timing timing.log`.
The output is sanitized by replacing the temporary fixture root with
`<fixture>` before recording. No production repository is used.

To repeat from the repository root, extract the base into a disposable folder,
then set `BASE_SOURCE` to that folder and run
`bash docs/demos/bare-source-hint/record.sh`.

This demonstrates source behavior only. Installed acceptance follows normal
review, merge, exact-main CI and scheduled updater gates.
