# Report the first failed exact read without repeating it

Run `PYTHONPATH=. python docs/probes/pr-demos/show-failure-once/probe.py`
from the checkout. It loads the baseline handler from `6b0083f6` and injects the
same unavailable SDK response into one exact-ID `show` call in each version.
The real handler makes **two SDK calls before, one after**, with the same error.
The probe makes no HTTP requests and requires no running tracker.

The original handler repeated its failed primary read to obtain stderr after
searching the configured stores. The change retains each failed observation's
diagnostic instead. Each store is attempted once; the next independent call
still reads afresh. A missing or foreign ID remains an error, and an exact
successful match still retains full item and dependency fields.

This demonstrates a pre-existing failure-path amplifier. It does not identify
the cause of a service incident, measure production HTTP calls per SDK command,
or establish a fleet query-rate reduction. No cache or timeout change is added.

Replay the retained demonstration with `scriptreplay -t timing.log output.log`.
