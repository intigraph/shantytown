# Retained daemon package demo

A synthetic stopped package migration used to remove the original payload tree
immediately. The candidate keeps it in quarantine: retained original trees 0 → 1,
retained bytes 0 → 16, while shared payload bytes remain 16. A real held-descriptor
control returns HOLD in both versions. Migration custody is stubbed in this fixture;
this does not prove a native daemon cycle or complete process visibility.

Before: `1920c0011f0309dbee2001bd9609edfc13bc161b`. After: the accompanying
`shantytown/codex_packages.py`; the PR caption identifies the demonstrated commit.

[Recording output](codex-package-quarantine.log) and
[timing](codex-package-quarantine.timing) are small retained repository artifacts.
Download both and replay with:

```sh
scriptreplay --log-out codex-package-quarantine.log --log-timing codex-package-quarantine.timing
```

The readable output log is also a transcript. Reproduce from the repository root:

```sh
git show 1920c0011f0309dbee2001bd9609edfc13bc161b:shantytown/codex_packages.py > /tmp/codex-package-before.py
python3 docs/demos/codex-package-quarantine.py /tmp/codex-package-before.py
python3 docs/demos/codex-package-quarantine.py shantytown/codex_packages.py
```
