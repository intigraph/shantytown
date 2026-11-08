# Deployment records stay out of ordinary hauls

Synthetic library demonstration: the same operation and ordinary work record
enter the committed base and candidate queue/resume functions. Before, both
records are offered; after, only ordinary work remains. Both inputs retain their
original state. This proves candidate selection behavior, not installed behavior.

Base: `6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf`. The candidate is the source
revision containing this recording; no behavior changed after recording.
Run from the repository root:

```sh
PYTHONPATH=. python3 docs/pr-demos/operation-haul/reproduce.py
scriptreplay --log-out docs/pr-demos/operation-haul/output.log --log-timing docs/pr-demos/operation-haul/timing.log
```

The small [output](output.log) and [timing](timing.log) pair is a downloadable
terminal recording; no inline player is claimed. [Reproducer](reproduce.py).
These sanitized artifacts remain in the existing PR demo directory with source
retention. No tracker, pane, deployment or network mutation is performed.
