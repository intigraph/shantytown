# Repository share alignment transport

The release builder passes the reviewed `docs/knowledge/alignments.ttl` to
native `share --alignments`. It requires the exported bytes to match that
source carrier, with `manifest.json` naming `files.alignments` as
`alignments.ttl` and sealing its SHA-256 in `alignments_hash`. It never repairs
an omitted member or manifest after export.

The packager and independent archive verifier allow only that exact reviewed
empty carrier. The member must be a regular file of at most 2 MiB; archive
paths, duplicate names and links remain forbidden. New publication provenance
binds the same bytes with `alignments_sha256`. The verifier checks this binding
after independently checking the archive checksum and manifest. Nonempty or
foreign carriers require a separate reviewed change.

Existing envelopes without an alignment member, declaration, seal or provenance
field remain readable. New builds require the carrier; an incomplete binding
fails rather than falling back to the legacy form.

`scripts/test-repository-share-publication.py` exercises the real packaging and
independent readback helpers with synthetic native output, including refusal
controls. This does not establish a native engine artifact, provider admission,
release publication or installed acceptance. Those require their own exact
artifact and deployment evidence.

## Explicit embedding provider

A new repository build requires these trusted-host inputs, with no ambient
configuration or model-cache fallback:

| Input | Meaning |
|---|---|
| `QUIPU_SHARE_MODEL_PATH` | Absolute path to the admitted ONNX model |
| `QUIPU_SHARE_MODEL_SHA256` | Lowercase SHA-256 of those exact bytes |
| `QUIPU_SHARE_TOKENIZER_PATH` | Absolute path to the admitted tokenizer |
| `QUIPU_SHARE_TOKENIZER_SHA256` | Lowercase SHA-256 of those exact bytes |
| `QUIPU_SHARE_EMBEDDING_DIMENSION` | Explicit integer output width, 1–4096 |

The existing engine source, CLI, companion server, and indexer pins remain
required by the publisher. The builder snapshots the two bounded regular files
into its private directory, verifies the bytes while copying, and configures
Quipu there with `[quipu.embedding]`. It does not configure the host or rely on
Bobbin's separate index-model setting. The exported `manifest.embedding` must
match the exact model and tokenizer digests and dimension. A missing or
different recipe fails before receiver admission or publication.

This source contract does not enable any producer or select model bytes.
Existing tagged releases and their artifacts remain unchanged. Adoption still
requires a qualified engine/provider combination, its native output-width and
receiver controls, and the managed publication route. Synthetic byte/config
tests prove the plumbing and refusal boundaries, not ONNX compatibility or
semantic-search readiness. The existing publication test entrypoint runs them
without loading a model or calling a production service.
