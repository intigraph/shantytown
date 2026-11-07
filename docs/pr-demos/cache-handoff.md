# Cache and handoff advice demonstration

A Codex usage fixture that the base ignores now yields measured request timing and
cache counters. Its model window is labelled as an assumption. A cold handoff
stays UNKNOWN; after a prior-handoff fixture is recorded, partial repository
overlap keeps a warm session and advises cycling after the configured window.

Base: `7923c5cfc68057406a39c4aee6479f6e509954bf`.
Demonstrated source: `c0d75e2` (the later caption commit changes documentation only).
The script loads the actual base implementation for the before result. It runs
entirely in a private temporary fixture: no live handoff, pane action, tracker
write, model call or measured cache eviction is claimed.

```sh
PYTHONPATH=. python3 docs/pr-demos/cache-handoff.py
scriptreplay --log-out docs/pr-demos/cache-handoff.output \
  --log-timing docs/pr-demos/cache-handoff.timing
```

[Recording](cache-handoff.output), [timing](cache-handoff.timing), and
[reproducer](cache-handoff.py) are retained. Terminal replay was verified;
reproduction requires the base commit in local Git history. Runtime acceptance
still requires normal installation and an observed real handoff.
