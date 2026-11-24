# Persistent daemon package pointer

The native updater can rewrite the shared `current` symlink through a card's
temporary runtime home. On base `4ac176316eea10d55745d1f7c3f72a70e777acc6`,
erasing that home leaves the selected payload missing. Source revision
`0fe211d2` retains the same release through a relative pointer, so the payload
still resolves after the same cleanup.

This is an isolated filesystem demonstration. Native updater behavior and mount
classification are modeled; symlinks, file removal, and installer locks are real.
It launches no Codex daemon and does not establish installed acceptance.

From the repository root:

```sh
python3 docs/probes/pr-demos/daemon-current/reproduce.py
scriptreplay --log-out docs/probes/pr-demos/daemon-current/output.log --log-timing docs/probes/pr-demos/daemon-current/timing.log
```

The [output log](output.log) and [timing log](timing.log) form a terminal recording
captured with util-linux `script`. Download both for `scriptreplay`; no inline
player is claimed. The output log is also a readable transcript. These small
artifacts are retained alongside the reproducer in Git.
