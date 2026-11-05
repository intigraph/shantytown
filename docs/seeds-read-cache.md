# Shared Seeds projection reads

Shantytown shares successful native projection reads between local processes.
Readers share the server's `/watermark` store identity and transaction for at
most one second, across queries and processes. A cache hit may therefore lag a
write or store replacement by that bounded window; after expiry, metadata must
be fetched successfully before cached rows can be reused.
A changed transaction or store forces a new query. A write during a fetch
prevents publication of that result: the post-fetch check always reaches the
server, even inside the shared window. Owner and graph constants remain in the
complete query key; existing server-side owner filters are preserved.

The private cache lives under `$XDG_CACHE_HOME/shantytown/seeds-reads-v1`
(default `~/.cache`). It holds at most 64 results of at most 1 MiB each, with
60-second maximum result age and bounded striped locks. Up to 64 small
watermark observations are retained separately, each reusable for one second. Slow lock acquisition falls
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

With `ST_SEEDS_PUSH_READS=1`, plate projections use the Seeds SDK private IPC
path instead, without watermark or primary query requests. See the push
projection contract in `adapters.md`. Query-only admission scopes retain their
original direct transport.
