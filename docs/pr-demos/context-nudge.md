# Earlier administrator context nudges

With a declared 1,000,000-token window and a 70% handoff hint, replay the same
synthetic administrator usage against base 42700874c0ef2207b54caaea619ff9bd5e8f7096
and source d40e5a71a21cd7a4ec131cc7b70385b39bc2a5ea.

Before: 55% produces no feedback; 70% emits once and remains silent at +120s.
After: 55% emits preparation feedback through PostToolUse and Stop; 70% repeats
at +120s despite intervening observations at +30/+60/+90s. Neither source schedules
a cycle or creates a sticky work ceiling.

This is a source-library fixture with an explicit test clock and isolated files.
It does not replay a real administrator transcript or prove installed delivery.
The actual capture command transport is covered separately by regression tests.
No live crew sessions, model/provider calls or tracker mutations are involved.

[Recording output](context-nudge.output), [timing](context-nudge.timing),
[reproducer](context-nudge.py). These small sanitized files are retained in this
repository's existing demo directory. Download both recording files, then replay:

```sh
scriptreplay --log-out context-nudge.output --log-timing context-nudge.timing
python3 context-nudge.py --source /path/to/source-checkout
```

Playback was checked with util-linux scriptreplay. This is a terminal recording;
no inline web player is claimed. Harness output contracts are documented by
[OpenAI](https://developers.openai.com/codex/hooks) and
[Claude Code](https://code.claude.com/docs/en/hooks#posttooluse-decision-control).
