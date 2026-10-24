# Shared Seeds projection reads

Shantytown shares successful native projection reads between local processes.
Each hit first checks the server's `/watermark` store identity and transaction.
A changed transaction or store forces a new query. A write during a fetch
prevents publication of that result. Owner and graph constants remain in the
complete query key; existing server-side owner filters are preserved.

The private cache lives under `$XDG_CACHE_HOME/shantytown/seeds-reads-v1`
(default `~/.cache`). It holds at most 64 results of at most 1 MiB each, with
60-second maximum age and bounded striped locks. Slow lock acquisition falls
back to a fresh query. Unavailable or malformed watermark metadata, unsafe
cache files, and cache I/O errors also use the original reader, never stale
cached success. Incomplete or failed query results are not cached.

Set `ST_SEEDS_READ_CACHE=0` to disable acceleration for rollback or comparison.
Explicit verbose profiling always executes the query. This is a disposable
performance cache, not an alternate work tracker or a background polling daemon.

## Reproduce the local control

Run `python -m pytest -q tests/test_seeds_read_cache.py` with the test extra
installed. The loopback fixture's twelve identical reads produce twelve queries
with caching disabled and one with caching enabled. It also checks transaction
invalidation, concurrent processes, metadata failures and query refusals.
These are private synthetic reads, not measurements of an installed service.
