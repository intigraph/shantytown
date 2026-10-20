# Isolated, key-derived agent identity

Without an installed protected policy, existing launches and declared actors
retain compatibility behavior. This is an explicit migration state, not proof
that agent identities are authenticated.

The operator-owned policy is `/etc/shantytown/identity.json` on Linux or
`/Library/Application Support/Shantytown/identity.json` on macOS. It must be a
root-owned regular file without group/world write access. Version 1 requires
`required: true` and a `users` object mapping distinct numeric UID strings to
`principal`, absolute `home`, HTTPS `endpoint`, and absolute trusted `sd` binary
paths. Dedicated agent UIDs must be at least 10000. No secret belongs in this
public policy. Do not point the trusted binary at an agent-writable executable.

With the policy present, ST asks that pinned `sd identity --json` to sign through
the existing Quipu session-attestation protocol. It pins HOME, endpoint and working
directory and removes environment configuration overrides. The result must match
the protected UID principal and be an attested session identity. Actor environment
claims and explicit senders cannot override it. Authentication failure refuses
before command execution; ordinary writes never gain a root-controller exemption.

Both harnesses pass through the same launch boundary. A separate trusted Linux
controller may drop to the bound UID/GID with no supplementary groups, privilege
gain or capabilities, and a positive environment allowlist. A process already
under its dedicated UID retains that UID. On macOS, enter the dedicated local
user before launching; this source does not migrate macOS accounts. Model
processes must have no sudo/root credential or controller socket that undoes the
boundary. Provider login enrollment, settings permissions, shared worktrees and
cross-host broker access need explicit migration checks under each dedicated UID.

Legacy SSH live relay carries only an environment sender. It refuses under the
protected profile until a key-authenticated cross-host broker is available.
Durable storage keeps the authenticated sender; failure of its optional live
nudge does not undo persistence. Do not disable the policy to restore that relay.

Stage compatible ST, Seeds and Quipu builds; create private user homes; enroll
own public bindings with the existing introducer; then verify own-key identity,
wrong/missing key refusal, replay refusal, and actual cross-UID file/signing denial
using temporary synthetic credentials. A same-UID 0600 positive control must
remain readable, demonstrating why a shared login is insufficient. Test both
harnesses and required write paths before installing the protected policy or
activating server key enforcement. Never copy an agent's private key to another.

Retain prior launcher/client/server configuration and the public binding inventory
for rollback. Move one supervised session at a time and run actual signed smoke
checks. A failed smoke requires the staged rollback, preserving credentials and
graph data. Removing policy, revoking keys, switching server authentication and
physical UID migration are security changes requiring the separately scoped
migration and rollback. Source tests do not establish installed acceptance.
