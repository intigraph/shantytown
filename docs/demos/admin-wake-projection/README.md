# Scoped administrator hook projection

The private fixture calls normal workspace provisioning on the retained
pre-fallback source (`ce995db60403bb1ccfd084a15cf2133f69b04ebc`) and the candidate.
An explicitly selected Claude administrator previously received zero budget
prompt hooks when its launch settings predated the feature. The candidate
projects one workspace hook without rewriting the shared role settings.

Run from a checkout containing the baseline commit:

```sh
python docs/demos/admin-wake-projection/probe.py
scriptreplay --log-out docs/demos/admin-wake-projection/output.log \
  --log-timing docs/demos/admin-wake-projection/timing.log
```

The [output](output.log) and [timing](timing.log) are an actual terminal recording;
download both for replay. They show OFF output bytes unchanged, ADVISE hooks
changing from zero to one, repeated provisioning retaining one, and OFF removing
the fallback. The script clears its environment and uses temporary workspaces;
it neither activates a live policy nor launches an agent.

Focused tests additionally cover tooling-kit and kit-free provisioning, other
administrators, workers, non-Claude harnesses, deselection, role-owned deduplication,
unchanged role-file identity/mtime, and preservation of unrelated hooks.
These source controls do not establish hot adoption by a running session.
Natural prompt/Stop observations and the separately approved trial remain required.
