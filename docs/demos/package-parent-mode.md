# Fresh package parent permissions

The same native `prepare` probe runs with a disposable fresh HOME and umask
`002`, without launching a daemon. Before: the shared package parent is `0775`
and its daemon child is `0700`; the parent fails the stopped-migration guard.
After: both are user-owned `0700` and the card link reaches the exact shared
destination. A restrictive-umask positive control also passes.

Create the immediate shared parent explicitly rather than allowing the child
directory's recursive mkdir to give intermediate parents the umask default.
Fresh preparation and stopped migration use the same private-parent check.
An existing unsafe parent retains its permissions and bytes and refuses with a
remediation hint. A parent symlink also refuses. No live payload is deleted and
no existing unsafe directory is silently chmodded.

The source controls cover prepare followed by stopped migration, retained
quarantine bytes, native locks, integrity, version, ownership and RAM-backed
destination refusals. They use disposable custody fixtures. Source success is
separate from the same installed probe and a normally authorized fresh natural
provision; no real crew restart or cycle is part of this demonstration.
