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
