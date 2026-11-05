# Optional signing observations

The Seeds tracker can select a reviewed per-agent signing profile for mutation
children. Default operation is unchanged when `/etc/shantytown/advise-signing.json`
(`/Library/Application Support/Shantytown/advise-signing.json` on macOS) is absent. This mode creates no keys, enrolls no trust, changes no Unix users and
enforces no identity. An operator installs the policy only after introducing the
keys, qualifying the normal writer and recording a rollback.

```json
{"version":1,"mode":"advise","profiles":{"worker":{"config_dir":"/var/lib/crew-signing/worker","config_sha256":"sha256-of-config-file-bytes"}}}
```

The policy must be a root-owned regular file without group/other write access.
Each profile directory and its `seeds` child must be owner-only 0700 directories;
`seeds/config.toml` must be owner-only, match the policy's SHA256 and explicitly
set `[quipu] require_identity=false`, `actor_principal_mode="observe"` and all
three signing fields. Preserve the original user destination/trusted-host policy
when preparing this config. Only the `sd` child receives its `XDG_CONFIG_HOME`;
the harness and other tools keep their configuration locations.

Before one mutation, the adapter runs `sd identity --json` with the same location,
working directory and child environment. A verified session identity selects the
profile; an unavailable or unqualified profile preserves the original writer
before the mutation and reports UNKNOWN. A mutation is never retried, including
after a timeout or refusal. Native Seeds still owns destination admission,
signature validation and its observe-mode actor policy.

Each selected-profile attempt appends a locked, fsynced observation to that
profile's `writes.jsonl`: asserted actor (including an explicit actor override),
verified principal/key ID/session, selection, timestamp, match and command exit.
This records the identity probe and command outcome, not independent proof of a
committed graph write. Read back the actual write for acceptance. Probe failures
record an unauthenticated legacy selection and cannot count as matching evidence.
Malformed policy and log failures warn UNKNOWN; diagnostics cannot refuse a
write. The log retains its beginning and stops appending at 16 MiB rather than
rotating away acceptance evidence. A full log or missing observations prevents
acceptance; it is not a zero-failure result.

This adapter covers `st` Seeds mutations, not direct `sd`, REST or MCP writers.
An acceptance window must enumerate and measure those other routes separately.
The declared runtime actor selects the profile: peers sharing a Unix UID can
borrow keys, and neither 0700 nor a root-owned selection map establishes peer
isolation. Enforced identity and distinct users remain separate deployment work.

Rollback: remove the optional policy to restore the original child environment,
verify the old writer, then revoke only the newly introduced sessions. Verify
revocation before removing their exact key files. Preserve observations, the
original host key/config and protected registry history.

See the [recorded fixture comparison](demos/advise-signing.md) for matching and
mismatched actor inputs on base and candidate source.
