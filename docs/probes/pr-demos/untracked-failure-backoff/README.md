# An unavailable hook read backs off without declaring an empty plate

Twenty separate hook invocations within twenty seconds previously called the
unavailable plate reader twenty times. The candidate calls it once within the
existing 60-second poll interval. Both versions return UNKNOWN without a warning.

```sh
PYTHONPATH=. python docs/probes/pr-demos/untracked-failure-backoff/probe.py
```

The probe compares actual handlers using a private clock and a private ledger.
It does not contact a tracker. Tests separately verify expiry, recovery, retained
escalation state and UNKNOWN activity even after an old hooked verdict. This
command-count change does not establish production traffic share or recovery.
