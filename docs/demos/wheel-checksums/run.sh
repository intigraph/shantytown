#!/bin/sh
set -eu
test -n "$RELEASE_ASSETS"
work=$(mktemp -d /tmp/shantytown-checksum-demo.XXXXXX)
trap 'rm -rf "$work"' EXIT
cp "$RELEASE_ASSETS/shantytown-0.4.0-py3-none-any.whl" "$work/"
cp "$RELEASE_ASSETS/shantytown-0.4.0.tar.gz" "$work/"
printf '%s\n' 'BEFORE: unchanged released pair has no checksum manifest'
if (cd "$work" && sha256sum -c SHA256SUMS); then exit 1; fi
printf '%s\n' 'AFTER: actual producer selects matching wheel/source metadata'
python3 scripts/release-checksums.py "$work"
(cd "$work" && cat SHA256SUMS && sha256sum -c SHA256SUMS)
printf '%s\n' 'NEGATIVE CONTROL: mutate wheel; the same manifest must reject'
printf '%s\n' 'tampered' >> "$work/shantytown-0.4.0-py3-none-any.whl"
if (cd "$work" && sha256sum -c SHA256SUMS); then exit 1; fi
printf '%s\n' 'Tampered wheel rejected (expected).'
