# Managed test hook caches and scrub coverage

A private test HOME creates two pre-commit dependency-cache repositories.
The baseline counts them as fleet coverage and then reports a drop when they
are cleaned up (5→3). The candidate reports constant operational coverage (3→3)
and counts those two caches as named exclusions. All three non-cache controls
remain armed: a normal workspace repo, an ordinary managed fixture repo, and a
cache-named repo outside the managed fixture pool.

[Recording](output.log.gz), [timing](timing.log). Private synthetic fixtures only;
no network, operational sweep, shared hook, production metrics or alert change.
Base4b3ae5e, tested runtime commit c28db3e; later commits only retain this demo.
The original terminal recording is byte-preserved in a small compressed artifact.
Download/decompress both files for playback; there is no inline embed claim:

```sh
gzip -dc output.log.gz > output.log
scriptreplay --log-out output.log --log-timing timing.log
```

Repeat with Bash, Python and Git:

```sh
python3 docs/probes/pr-demos/scrub-managed-cache/reproduce.py
```

This demonstrates one known dependency-cache contribution, not exhaustive fleet
visibility or a guarantee that every denominator change is harmless. Normal
review, CI, installation and scheduled observation remain separate.
