# Cycling with independently retained Git work

Normally, commit and publish work before cycling. An archived repository or a
publication gate can make that impossible. `st agent cycle` can instead read
`--bundle-custody-item ID` (repeatable): a specific clean local branch is covered
by an independently verified, root-accepted full-history Git bundle. This is
custody, not `--allow-loss`, permission to push, or permission to delete a ref.
Dirty tracked files and unrelated unpushed trees still refuse.

The existing configured tracker supplies comment authors; JSON cannot declare
its own accepting identity. The accepting author must currently have the
administrator role with no lead. A registered crew member other than the target
agent must independently verify the bundle and attest the exact receipt digest
on the same item; the accepting root may also be that verifier. These are crew attribution checks through the
existing trusted tracker/card boundary, not cryptographic signatures.

Use a full bundle containing the exact `refs/heads/...` branch and all history,
not an incremental bundle. The independent verifier checks the SHA256, exact
listed branch/head and `git bundle verify`, and retains a recoverable full
archive. Put this exact JSON payload after `cycle-bundle-accepted-v1 ` in a root
comment (one receipt per comment, no Markdown fences or extra fields):

```json
{"agent":"worker","tree":"/absolute/owned/tree","ref":"refs/heads/topic","head":"<full commit OID>","bundle":"/absolute/archive/work.bundle","sha256":"<64 lowercase hex>","reason":"archived"}
```

`reason` is either `archived` or `gated`. The independent verifier's comment is
exactly `cycle-bundle-verified-v1 <digest>`, where digest is SHA256 of the receipt
JSON encoded as UTF-8 with sorted keys and compact separators (`(',', ':')`).
A matching digest is required; acceptance of another payload does not transfer.
Retain the comments and bundle: a local path alone is not root acceptance.

At actual cycle preflight, the command rereads both item comments and current
cards, checks the current tree's symbolic branch and full HEAD, hashes the
regular non-symlink bundle, refuses prerequisite history, runs Git's bundle
verification and checks the exact listed ref/head. It rechecks file identity and
hash after verification. Unknown, missing or changed inputs refuse custody;
there is no fallback to an unverified receipt. Bundle input is capped at 2 GiB,
header at 10,000 bounded lines, digest at 30 seconds and each Git read at 15
seconds. This does not unpack a bundle, revalidate every archived object or
restore from it: the independent full-archive verification remains essential.

The item IDs survive a `--self` request and are revalidated by its eventual
server. A replacement request does not inherit them. The normal durable
checkpoint, graph context, governor, ownership and lifecycle gates still apply.
Existing outage/authority notices and the explicit `--allow-loss` behavior are
unchanged when no custody receipt is supplied. No bundle is created, no archived
push is attempted, and no worktree is cleaned by this feature.
