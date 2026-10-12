The same sandbox input accepts a valid tag/commit identity on both revisions. A wrong triggering SHA passes the former gate and fails the new gate. This proves the source gate, not a hosted release or installation.

Base: `0a5cd6ac5083c8b86c1622b21d04375501e304c4`; changed workflow: `80bc60e`. Later demo-only commits preserve that workflow. Repeat with `python3 docs/demos/release-gate.py`. The fixture creates its own Git repository and copies its interpreter; it contacts no forge.

[Output recording and transcript](release-gate.log), [timing](release-gate.time). Download both and run `scriptreplay --log-out release-gate.log --log-timing release-gate.time`; playback was checked locally. No inline player is assumed. These small sanitized artifacts are retained with this demonstration.
