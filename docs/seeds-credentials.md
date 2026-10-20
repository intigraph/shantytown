# Explicit private Seeds commands

The opt-in adapter is separate from ordinary tracker routing:

```sh
python -m shantytown.seeds_credentials --root /path/to/deployment --agent alice -- show example-id --json
```

It uses the existing deployment-owned `crew-credentials.json` selection and its
`quipu_cli` reference. It does not enable that selection, issue credentials, or
change a running session. The installed `sd` must support the
`seeds-credential-admission/v1` contract and destination-bound descriptors.
An older CLI refuses before any provider request.

For a selected command, the adapter first asks the native CLI to admit the same
operation, working directory and resolved destination, without executing the
operation, opening a store, reading a token file/descriptor, or making HTTP
requests. Native trust, transport and signing compatibility checks apply. A
local store, untrusted project destination, unsafe transport or malformed URL
refuses before the provider is called.

Only then does the adapter fetch the exact selected reference. It never calls
the MCP header helper's shared fallback. Missing, denied, stale or malformed
selected credentials refuse the command. There is no same-command shared retry,
including after an authenticated server refusal.

The bearer lives in a sealed anonymous Linux memory descriptor passed only to
that child. The environment carries a principal declaration, descriptor number and the exact
admitted destination; it carries no selected bearer. The declaration is
`principal-sha256:` followed by the lowercase SHA256 of the selection principal's
exact UTF-8 bytes. This supports canonical IRIs while respecting native Seeds'
restricted metadata alphabet. There is no URI normalization or change to provider
selection: the reference and its key remain bound to the original canonical
principal. The digest is a non-authenticated declaration, not a substitute for
server-authenticated attribution. Native code checks the resolved
destination again before reading the descriptor. A configuration change between
admission and execution cannot silently retarget it. The launcher closes its
descriptor on success, errors, timeout and interruption. Unsupported descriptor
platforms refuse before provider access; there is no disk-file fallback.
Captured child stdout/stderr redact the exact selected bearer and up to two JSON
escaping layers, including a server error that echoes it. The operation exit
status is preserved; redaction does not authorize a retry. This is not a promise
to recognize arbitrary encodings of credential material.

Both inherited Seeds bearer inputs, legacy `SEEDS_TOKEN`/`QUIPU_AUTH_TOKEN`
aliases (including the Quipu token-file alias), and all Seeds selection metadata
are removed from the child environment. No alias is mapped into a native input.
The parent environment is unchanged. Explicitly
deselected commands use native user/config defaults after that sanitation; this
adapter does not treat inherited environment bearers as deliberate overrides.
Callers needing explicit overrides must use the native explicit input API.
An MCP-only selection does not implicitly select a Seeds credential.

This is a source capability. Publication, installed artifact identity, actual
authenticated server attribution, explicit SDK integration and activation are
separate acceptance gates. The loopback fixture tests observe bearer headers;
they do not establish a production authenticated principal.

Run the paired-source fixture with a private native candidate:

```sh
SEEDS_ADAPTER_TEST_BINARY=/path/to/private/sd python -m pytest -q tests/test_seeds_credentials_cli.py
```

`SEEDS_ADAPTER_LEGACY_BINARY` optionally supplies an older private binary for the
zero-provider-call refusal control. Neither test variable installs a binary.
