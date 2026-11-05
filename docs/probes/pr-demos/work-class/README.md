# Author/reviewer work-class admission

The same private normal `go --dry-run` calls exercise the unchanged authoritative
work labels before and after the correction. The baseline refuses Codex for
important/design authoring and admits a Claude worker for important work. The
candidate admits Codex and refuses that Claude worker. Review work remains on
Codex. Every call leaves its private tracker unchanged and sends zero pane input.

Baseline: `c7eb531` (the full immutable revision is in the recording). Candidate
module SHA-256: `d0b712ec863c2e24c9d3d4c568f3fccc1e1b8fb539a6f08cbba9c08cedb850c7`. The published PR head identifies the
corresponding source revision; documentation and recording additions do not
change this module fingerprint.

The [recording](demo.output.gz) and [timing](demo.timing) preserve the real
util-linux `script` output and timing. This is a terminal recording, not an
inline video. Download and replay from this directory:

```sh
demo_log=$(mktemp)
gzip -dc demo.output.gz > "$demo_log"
scriptreplay --log-out "$demo_log" --log-timing demo.timing
rm -- "$demo_log"
```

Repeat with the repository's declared test dependencies installed:

```sh
python3 docs/probes/pr-demos/work-class/demo.py
```

The driver loads the immutable baseline and candidate module into its own
process, uses the existing private FilesTracker/NullPanes fixture, and invokes
the normal CLI admission path. It never invokes the installed CLI or selects
a deployment root. This demonstrates source behavior only; a live dispatch
requires normal reviewed delivery and verified installed source identity.

The small sanitized recording is retained in Git with this caption and runner.
Normal CI, independent review and installed acceptance remain separate gates.
