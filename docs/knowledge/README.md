# Reviewed knowledge witnesses

The registry preserves reviewed summaries on actual indexed source identities.
The renderer refuses absent or ambiguous pointers, source paths outside the
materialized release, invalid content and missing freshness metadata.

Eight entries retain strict `source_sha256` witnesses: changing their source
requires an explicit registry update. Unknown modes and mixed declarations fail.

The CLI interface alone uses explicit `source_hash_mode: release-bytes`.
Its emitted `sourceHash` is computed from the exact published `shantytown/cli.py`
bytes. Its curated summary lives in `cli-summary.md`, bound by the registry's
strict `summary_sha256`. Missing, changed, relocated or escaping summary sources
refuse publication. The renderer still checks the summary's content and exact
indexed CLI identity; it does not mint an alternate document identity.

This separates two claims: the published CLI bytes are identified exactly, and
the summary is the explicitly reviewed anchor. A CLI edit does not certify that
its summary was reviewed again. Neither derivation nor a source edit renews
`reviewed_at` or `source_revision`. Summary changes require a deliberate anchor
and witness update; competing summary edits must still be reconciled by a human.
Do not generate, discard or union semantic summary changes to avoid conflicts.

Disjoint CLI-only branches now leave the registry and summary anchor unchanged,
so both merge orders preserve the same source and render its new byte hash.
Existing branches which still update the removed CLI digest or inline summary
may need one real migration conflict resolution. This is not an automatic cure
for old conflicting summaries. Other source records do not inherit this mode.

Run `python3 scripts/test-repository-knowledge.py` for both merge orders, the
old committed-digest conflict and strict witness/path/content refusal controls.
