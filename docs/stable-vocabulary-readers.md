# Stable vocabulary readers

Workflow-run and signed-gate queries accept the exact historical and published
spellings of twelve mapped vocabulary terms. They use explicit grouped UNION
patterns for older native literal readers, retaining the configured graph or
open-windows dataset. Unknown terms have no inferred namespace fallback.
The independent ownership snapshot is `tests/fixtures/writer-reader-ownership.json`.

Conflicting gate alias values refuse rather than overwriting a row and accidentally
approving it. Local pinned signer checks, signature bytes, configured-graph scope
and Quipu recorded-witness trust checks are unchanged. GateApproval is published
as `https://w3id.org/intigraph/quipu/ns#GateApproval`, so a gate typed with
either spelling is read; a look-alike class in another namespace is not.

### Remaining `aegis.gastown.local` occurrences, classified (aegis-m5s.3)

| Where | Class | Status |
|---|---|---|
| `stable_vocabulary.LEGACY`, `seeds_plate.BLOCKED_ON`, `quipu_jobs.QUECHUA` | former-name alias, read only | kept, labelled |
| `gate_verdict` reader: `aboutGitHubEntity`, `recordedAt`, `authorAgent`, `evidence`, `authoredByAgent` | vocabulary term with no published w3id term | exact historical reads until published |
| `gate_verdict` writer: every gate and verdict predicate and class | vocabulary term | still the historical spelling, see below |
| `gate_verdict.pr_iri`, `gate_approval.*`, `gate_verdict.*`, `job_mailbox` proof pattern | deployment instance IRI | shared contract with camayoc `github_ingress.node_name` and chaski, so not changed in this repository alone |
| `scripts/build-repository-*`, `queries/repository-share-*.rq` | former-name source identity for repository shares | kept (aegis-ro425e.18) |

`shuttle_runs` no longer carries an unused copy of the legacy namespace.

This is a reader-first source slice. Signed writer output stays unchanged until
the Quipu native witness prerequisite supports canonical signatures and is
installed. Tests deliberately retain the actual legacy native-witness model;
canonical-only signatures are discovered by the new reader and then refused by
that existing backend. No twin signature writes or trust-root bypass is introduced.
Vocabulary publication, instance identity, registration, profiles and runtime
adoption each retain their own gates. This repository's main source refresh has
live consumers, so merge/adoption requires its normal explicit disposition.

See the [private SPARQL recording](demos/stable-vocabulary-readers/README.md).

Job catalogue decoding also accepts the three exact published Quechua spellings
of sourceKind, owner and enabled. RDF term metadata and incoming response bytes
remain intact; contradictory old/new enablement refuses. This enables read
compatibility with the Chaski catalogue adapter source slice, without changing
any schedule, declaration or runtime job.

The native Seeds item, readiness, ready-count and ranking dependency readers also
accept the exact published Quechua blockedOn edge. Both spellings invalidate
owner-membership caches. Wire kinds, selected subjects, graph-local blocker
status and existing readiness meanings remain intact; a renamed edge cannot
silently become a contextual dependency or an apparently unblocked item.
