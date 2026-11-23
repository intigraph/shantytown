# Concurrent stale-read coalescing

This is a local source fixture, not an installed-service test. Eight simultaneous
callers request the same populated query inside `stale_ok()`. The base issues
eight wire queries; the candidate issues one. Both return eight populated
answers. An exact read afterward still issues one additional wire query on each.

The base is `e0a982d8fb74fafe870e2c6ad88c3b6d54b41188`. The transcript identifies
the exact reader and flight sources by SHA256. Repeat against either source tree:

```sh
python3 docs/demos/stale-read-singleflight/demo.py --source-tree /path/to/source
```

The script uses a private temporary cache and a loopback fixture server. It does
not query a configured Quipu service. [The actual transcript](transcript.txt)
is retained here with this change. This is text evidence, not a terminal
recording; the qualification was not captured with a terminal recorder.

Flight waiting is bounded; failures do not produce cached empty answers. Exact,
projection, snapshot and direct reads do not enter this flight path. This demo
does not establish a live request-rate reduction or the fleet's longer acceptance
window. Disable the bounded-staleness tier with `ST_SEEDS_STALE_TTL=0` to roll back
its coalescing.
