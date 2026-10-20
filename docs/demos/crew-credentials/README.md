# Volatile credential source demonstration

Run `python3 docs/demos/crew-credentials/demo.py` from the checkout. The same
helper input is translated on base f057406faf225701fdeb61a3de920a8d733a7757
and the candidate implementation accompanying this recording. The base retains
the Claude-only field; the candidate selects Codex's native field.

The candidate then materializes a synthetic named credential in a private
fixture directory at 0600. Persistent MCP configuration contains no named bearer.
Deleting that file makes the next helper invocation select the synthetic shared
credential. This is fallback at invocation/reconnect, not revocation.

The fetch and runtime directory are synthetic; actual private HTTP and runtime
mount refusal controls are separate tests. No real credential, network service,
installed client, or production filesystem is used by this demonstration.

[Output](output.log) and [timing](timing.log) form a replayable terminal recording:
download both and run `scriptreplay --log-out output.log --log-timing timing.log`.
Replay verified locally. These small sanitized artifacts are retained here with
the source so they remain reviewable without a separate artifact service.
