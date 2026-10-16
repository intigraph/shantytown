# Natural-event resume conditions

Source-library fixture, not an installed or production result. The same event
marker is UNTESTABLE on base `be8eba5a`; the candidate recognizes it. A complete
natural pair is MET, a manual recycle is NOT_MET, and a wrong generation is
UNKNOWN. The demo uses an explicitly accepted synthetic binding; the real
initial binding remains disabled pending its producer owner's acceptance.

Run from the source root with the test dependencies installed:

```sh
PYTHONPATH=. python3 docs/demos/natural-resume/probe.py
scriptreplay --log-out docs/demos/natural-resume/output.log --log-timing docs/demos/natural-resume/timing.log
```

The output/timing files are a terminal recording with a readable transcript;
there is no inline video player. Candidate source SHA256 values in the recording
identify the demonstrated files without a self-referential commit hash. Tests
add bounded file reads, scratch tracker write/read-back, and scheduled release
with a fresh evidence check. The recording does not prove a natural production
event occurred or authorize enabling a binding.
