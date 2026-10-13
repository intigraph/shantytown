# Release checksums

Shantytown publishes a Python wheel and source archive. After the existing test
and build gates, the release workflow creates `SHA256SUMS` for that exact pair,
then verifies it before the installed-wheel console proof and again before upload.

The producer requires exactly one pure-Python Shantytown wheel and one source
archive. Package names, versions and filenames must agree. Missing or duplicate
artifacts, symlinks, extra files and existing manifests refuse publication.

Download the wheel, source archive and checksum asset from the selected release
and verify their bytes before installation:

```sh
sha256sum -c SHA256SUMS
```

The manifest contains exactly one wheel entry. Automated consumers should also
compare that digest with their independently reviewed pin; agreement with a
checksum downloaded alongside an artifact is not independent source review.
An older release may need a separately reviewed checksum sidecar for its existing
assets. Adding that sidecar does not rebuild or replace its wheel or change its
version.
