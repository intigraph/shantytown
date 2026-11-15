# Registered hook drift: source fixture demonstration

Trigger: a shared Stop registration targets the conventional canonical capture
hook, but its bytes differ from the declared skill source. The fixture calls
real `provision()` and checks both bytes and nanosecond mtimes of the registration
and canonical hook. A matching-hook control verifies the receipt and repeats
provisioning to check idempotence.

Base: `ea5608bcaedd7405c7815b708b576e0f4d8f65ae`.
Candidate: the commit containing this demonstration (see PR head).
Target: isolated source fixtures, not an installed crew or live service.

[Before transcript](before.txt): the regression failed with `DID NOT RAISE`;
provisioning incorrectly succeeded. [After transcript](after.txt): the same
regression and matching-byte control pass, together with missing, nonexecutable,
symlink, source-authority, override, retirement and receipt-write controls.
The HOME guard verifies production paths and UID resources stayed unchanged.

Repeat with the repository's test dependencies:

```sh
python3 -m pytest -q tests/test_provision_legacy_capture.py
```

These are excerpts of actual captured test output. A terminal recording is
unavailable because asciinema is not installed. Transcripts are retained in Git
with this small fixture demonstration; they prove source behavior only.
