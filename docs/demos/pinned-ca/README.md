# Protected job CA configuration demonstration

The same protected identity policy changes from an unsupported binding refusal
on base `9697c751` to selecting the operator's Seeds config in the identity
subprocess. Changed CA bytes then refuse before invoking sd. UID/ownership checks
and the sd identity response are mocked; config files and SHA-256 are real.

[Output](output.txt) and [timing](timing.txt) form a terminal recording:

```sh
scriptreplay --log-out docs/demos/pinned-ca/output.txt --log-timing docs/demos/pinned-ca/timing.txt
PYTHONPATH=. python3 docs/demos/pinned-ca/demo.py
```

The demo loads the baseline actor module with `git show`, then the candidate
checkout. The PR body identifies the exact candidate commit. It neither changes
UIDs nor installs policy, copies keys, contacts a server or proves native Mac
readiness. The separate tests also cover tracker reads/writes and both native job
exec and attestation environment propagation. Download both files for
`scriptreplay`; no inline player is promised. These small artifacts remain in Git
with the reproducer.
