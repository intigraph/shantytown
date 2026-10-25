# Stopped-owner lifecycle observations

The local stop/ceiling, launch, heartbeat and existing supervisor hooks can publish
observed lifecycle facts for a read-only held-work consumer. Publication is off
unless `SHANTY_OWNED_WORK_PUBLISH=1` in the environment or the crew root's
`[env]` configuration. An explicit environment value overrides the root setting.
Existing hooks read the root setting without relaunching agents. Configure the normal Quipu endpoint,
namespace and accepted writer credential through the deployment's usual paths.
Missing or refused credentials retain pending local evidence and report UNKNOWN;
publication never repairs credentials or substitutes a broader writer.

Each lifecycle observation is an existing governed `OperationalFact`, with
`sourceKind`, `ownedBy`, `observedAt`, `reviewAfter`, canonical JSON in its comment,
and `schema:version`. It never edits CrewMember status. The durable writer counter
advances before state, so a crash may leave gaps but does not reuse revisions.
An explicit stop ignores delayed heartbeats; a sanctioned launch supersedes it.
Live heartbeat observations renew at most once per five minutes. Evidence older
than the 30-minute lease is UNKNOWN, not proof of death or proof of continued life.
Local lease expiry is also published with a newer writer revision and the
original observation time. Consumers label that state UNKNOWN even if a clock
shift makes the timestamp look recent. No native engine expiry capability is claimed.

An immutable fact is read back before its local receipt advances. A lost response
is reconciled on a later hook by exact point read, without blindly resending.
The deterministic current-head OperationalFact is only a projection of verified
receipts; it is not the historical source. Its single JSON comment is replaced
atomically through `/set`, avoiding an unbounded latest-revision history query.
Partial coverage is explicit. Each changed head has a strictly increasing head
revision; source state revisions are separate and may contain gaps.
The head also retains a bounded `agent_versions` map: each published agent's
revision and canonical payload digest. These fences survive omissions from
partial heads. A second agent's newer revision cannot mask a replayed older
state and receipt, nor can an equal revision publish changed content. A known
source agent disappearing from local state is refused. Pending coverage remains
partial; it never clears the last published fence. The map shares the existing
100-agent and 64 KiB head bounds and needs no lifecycle history scan.

`/set` is not compare-and-set. A separate nonblocking `graph.lock` serializes the
entire remote head read, write and read-back across lifecycle and supervisor
publishers. It never holds the heartbeat/state lock during HTTP. This lock is
host-local: source and head identities include the host and resolved crew root,
and a prior head naming another host is refused. A consumer must pin exactly
one expected source/head and host, never merge same-named agents across hosts.
A local state replay older than the remote head is refused. A durable head receipt also refuses a missing,
rolled-back or changed receiver head; a server reset is not an empty new crew.
Retained pre-publication state receives writer revisions without renewing its
original observation time. Missing, ambiguous,
expired, conflicting or truncated evidence must never mean an empty healthy crew.

Delivery starts at most four pending agents per invocation, with a five-second
start budget and three-second HTTP deadlines. One immutable fact and its point
verification precede head advancement. The head is bounded to 100 agents and
64 KiB. Source state, counters and receipts must survive source upgrades and
rollback; do not clear them to make a failed publication pass.

Rollback: disable the publication setting through the normal configuration lane,
then roll source back through the reviewed release/install path. Retain all local
state, writer counters, receipts and graph history. Readers continue to show
expired evidence as UNKNOWN. No agent lifecycle or ownership change is part of
this rollback.
