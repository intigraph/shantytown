# Exact-context command consumer

The same console-entry lookup finds no `st-context` entry on base
`8181b7f8e8575b703f5efc8b34b83d53e706d0bf`, and finds the exact-item reader
on implementation `14cfe3c6964b7740e77a55fc3d8187fcdb71530a`.
The recording then calls the candidate command's actual `main` with a synthetic
tracker: linked evidence retains its record/source identity, a failed ruling
read remains UNKNOWN, and unavailable deployment selection returns failure
without disclosing its diagnostic. The query-first directive names this reader
before semantic search.

Reproduce from the repository root:

```sh
python3 docs/demos/exact-context-consumer/demo.py
scriptreplay --log-out docs/demos/exact-context-consumer/output.log \
  --log-timing docs/demos/exact-context-consumer/timing.log
```

[Terminal output](output.log) and [timing](timing.log) are retained in this
repository beside the reproducer; download both for replay. This is an
output-and-timing terminal recording, not an inline video. Later demo-only
commits retain the demonstrated implementation unchanged.

Limits: the base comparison reads its actual packaging manifest; it does not
execute a nonexistent base command. The candidate uses explicit synthetic
transport and context fixtures, not a live graph or an installed console script.
Reader completeness, deployment propagation and live provenance require their
own acceptance checks.
