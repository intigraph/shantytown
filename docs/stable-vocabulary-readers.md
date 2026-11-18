# Stable vocabulary readers

Workflow-run and signed-gate queries accept the exact historical and published
spellings of eleven mapped vocabulary terms. They use explicit grouped UNION
patterns for older native literal readers, retaining the configured graph or
open-windows dataset. Unknown terms have no inferred namespace fallback.
The independent ownership snapshot is `tests/fixtures/writer-reader-ownership.json`.

Conflicting gate alias values refuse rather than overwriting a row and accidentally
approving it. Local pinned signer checks, signature bytes, configured-graph scope
and Quipu recorded-witness trust checks are unchanged. Unpublished GateApproval
and GitHub property references remain explicit historical reads pending ownership.

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
