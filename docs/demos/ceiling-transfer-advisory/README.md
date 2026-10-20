# Ceiling-transfer observation demo

Same isolated sweep fixture on base `1277d0a4b9ad92c53e0abc12b769eb0694e3238c`
and the candidate producer hashes printed in [the transcript](output.txt):

- Ready receiver: one confirmed send and comment on both versions. Base has only
  the legacy success ledger; candidate adds start, plan and outcomes observations.
- Dispatcher raises an unproven-send error: one attempt, no success ledger or
  comment on either version. Candidate still records inputs and the unproven
  outcome. All candidate observations remain ungraded.

Reproduce each leg with the SAME [probe](demo.py), from separate processes:

```sh
python3 docs/demos/ceiling-transfer-advisory/demo.py /path/to/base BASE
python3 docs/demos/ceiling-transfer-advisory/demo.py /path/to/candidate CANDIDATE
```

The source trees need their test dependencies. The probe uses the existing
injected sweep fixture and temporary roots; it sends no live work. The readable
transcript is normalized from an actual terminal recording (CRLF to LF, recorder
metadata omitted); the original output/timing pair is retained with the private
work-item evidence and replay was checked. No inline video playback is promised.
Producer hashes, rather than documentation commit identity, bind this recording.
No natural sweep, installed-process identity, operational cost, independent
judgment or measured false-positive rate is demonstrated. The rate remains
UNKNOWN until natural rows are independently adjudicated.
