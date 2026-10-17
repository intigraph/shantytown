# Crew credentials at launch

This path is off unless deployment supplies a private, user-owned
`provision/crew-credentials.json` with `enabled: true` and an explicit agent
selection. It changes authentication for existing canonical MCP server names;
it does not declare servers or replace the tooling manifest.

At ordinary provisioning, Shantytown reads the selected agent's exact secret
reference from Infisical using the existing crew machine identity in
`~/.infisical/credentials`. It reads only the selected path/key, pins secret ID,
version and SHA256, refuses redirects, and makes no retries. Login and secret
read each have a five-second socket timeout and a bounded response. This is not
a guaranteed total wall-clock deadline for a continuously streaming server.

A successful read creates a regular 0600 file under
`/run/user/<uid>/shantytown-credentials/<agent>/<server>`, beneath verified
user-owned 0700 directories on tmpfs. The per-crew bearer is not written into
persistent harness config, an env file, or a pane environment. A normal relaunch
rematerializes it; reboot clears it. Disabling the feature does not revoke any
server-side credential. Removing an old runtime directory is an operator cleanup,
not a revocation mechanism.

The harness receives a header-helper command, not a bearer. Claude uses
`headersHelper`; Codex uses `http_headers_helper`. Static Authorization is
removed so it cannot override the helper. Other headers remain. OpenCode is
unsupported for this opt-in path and refuses before rewriting the kit.

If the selected secret cannot be fetched, the prior launch's file is removed.
The next helper invocation uses the existing global shared credential provider,
never another crew member's override. A missing or invalid shared credential
refuses rather than emitting empty authentication. The helper's JSON output is
for the harness's private pipe: do not run it into a terminal or capture its
stdout in diagnostics.

**Fallback occurs on the next helper invocation or reconnect.** Codex caches
headers for an existing connection; deleting a runtime file does not replace
already cached headers and is not token revocation. Phase 1 retains shared and
named server acceptance. No forced session cycle is required or authorized.

Example configuration (all values synthetic; the actual reference comes from
the reviewed issuance receipt):

```json
{
  "version": 1,
  "enabled": false,
  "server": "https://secrets.example.invalid",
  "agents": {
    "alice": {
      "principal": "urn:crew:alice",
      "servers": {
        "homelab": {
          "audience": "homelab-mcp",
          "project": "example-project",
          "path": "/mcp-crew/alice",
          "key": "CREW_<FIRST_24_UPPERCASE_SHA256_OF_PRINCIPAL>_HOMELAB_MCP",
          "secret_id": "receipt-secret-id",
          "secret_version": 1,
          "token_sha256": "<64 lowercase hex characters from receipt>",
          "shared_key": "HOMELAB_MCP_TOKEN"
        }
      }
    }
  }
}
```

Supported audiences are `homelab-mcp` and `quipu`. Paths must match the selected
agent exactly. Drift verification constructs the expected helper configuration
without fetching secrets, touching runtime files, or making network requests.
Source tests and a native config-parser check do not establish installed client
adoption, end-to-end identity, or a complete attribution measurement. Rollout
still needs server acceptance first, the scoped deployment slot, a logged
one-agent canary, fleet order, and the separate measurement.
