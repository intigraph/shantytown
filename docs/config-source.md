# Graph configuration and shared instructions

An operator can select one read-only Quipu configuration document with
`SHANTY_CONFIG_ENTITY` and `SHANTY_CONFIG_SERVER` in the deployment's TOML `[env]`.
All three selectors are local bootstrap facts. The document cannot redirect its own
reader. No configuration source is enabled by default.

Precedence is explicit command flags, local TOML, Quipu settings, the retained
local env.json defaults, ambient environment, then built-in defaults. The existing
tracker selector consumes the resolved configuration; no remote failure selects
another tracker. Local tracker declarations therefore remain a recovery control.
Set an explicit local backend for a cold deployment without an accepted cache.

The source has exactly one `rdf:value`, containing unique-key JSON with references to governed fragment nodes:

```json
{
  "version": 1,
  "settings": {"env": {"SHANTY_BACKEND": "seeds"}},
  "fragments": [
    "urn:example:instructions:fleet"
  ]
}
```

Settings use the existing TOML configuration schema; unknown keys are refused.
Literal credentials and bootstrap selectors are prohibited in the document's
`env`. Secrets remain in the existing local credential mechanism. Instruction
text is public operational policy, never a secret store. Operators must not
place credentials in text or arbitrary settings.

A bounded query reads the selected document, then one VALUES query resolves its
maximum 128 exact fragment references. Each network call has a one-second timeout.
`SHANTY_CONFIG_FRAGMENT_CLASS` names the governed fragment class in the local
bootstrap configuration. Its namespace supplies instructionScope and
instructionSelector; each typed fragment has one rdf:value text body. Missing,
untyped, duplicate or incomplete rows refuse the fresh document.
A provision/launch CLI invocation shares one validated snapshot, avoiding
repeated graph reads by its configuration consumers. The next provision reads
fresh. Ordinary reads, including anchor, read the accepted cache without network
requests or cache writes; a missing cache produces a visible warning and keeps
local declarations. Invalid bootstrap selectors refuse a guessed tracker. A validated
source-bound last-good JSON cache is written atomically with private permissions.
On unavailable or invalid graph data, the reader validates the matching cache
again and emits a visible warning. Without a usable cache it keeps local
configuration and instruction files, also with a warning. A different server or
entity has a different cache; it cannot borrow another source's last-good data.
When a validated first-class source is configured, provisioning also caches the
validated canonical tooling manifest, bound to both its source and the config
bootstrap. A tooling read timeout can use that accepted snapshot with a visible
freshness warning. Credential placeholders are cached before local expansion;
credential files and live kit validation remain authoritative. Missing cache or
malformed fresh manifest still refuses. Existing deployments without the new
source retain their fresh-only contract, and health inspection still asks for
fresh graph evidence.

`st ops provision --instruction-report` prints winning declared-key sources and
before/after hashes, byte counts and equality for each selected agent. It prints
no credential values or instruction bodies and does not provision files. Keys
absent from the source report retain existing local/ambient/default resolution.

Instruction fragments concatenate exact text in fleet, role, agent, harness
order; within a scope the source document's list order wins. Non-fleet fragments
require a selector. Both CLAUDE.md and AGENTS.md receive the same rendered body;
local identity files, skills, hooks and credential files remain separate.
External instruction symlinks and shadowing AGENTS.override.md are refused.
The existing tooling projection still owns its canonical block and attachments.

Migration defaults to `SHANTY_INSTRUCTIONS_MODE=compare`: collect the current
fragments and verify byte-for-byte equality before enabling `apply`. The current
files remain authoritative in compare mode. An operator enables apply only after
reviewing the exact source, provenance and comparison packet. Existing sessions
are not claimed to reload; verify actual files after neutral propagation and a
real next provision. A graph outage with a matching last-good document preserves
its render. Do not edit a host's live instruction or skill symlink by hand.

The document and fragment RDF types require the deployment's governed vocabulary
and shape-owner review. This source implementation does not mint types, accept
shape proposals, or activate graph policy. A new fragment type must be proposed
and persisted in the server's shape files before cutover.

## Work items without tracker-specific instructions

`st task TITLE` creates work. `st anchor AGENT` reads the current plate.
`st work item show ID`, `update ID`, `comment ID --file BODY` and
`close ID --reason-file REASON` use the configured tracker. `update` supports
status, assignee, priority, description-file and notes-file; terminal transitions
require `close` and its evidence file. `--dry-run` prepares writes without applying
one. Existing `st work defer` and `repool` retain their verified lifecycle guards.

Exact-ID readback precedes writes, and update/close/comment readback verifies the
result. A timeout or unproven readback is an indeterminate write: inspect the
known item, never automatically resend. A tracker that cannot support a comment
or verify terminal evidence refuses before that operation. The Tracker protocol
remains get/update/create; backend helpers own comments and transport details.
