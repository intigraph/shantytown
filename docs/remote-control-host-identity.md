# Private Remote Control display hostnames

A private UTS hostname also affects tool shells and hooks descended from the
Codex app-server. Without a separate physical-host value, it changes lifecycle
producer hashes, Quipu attribution and governor telemetry instances. A configured
fleet-host alias is a different identity and must not replace an existing
physical-host hash.

The Codex launcher captures `SHANTY_PHYSICAL_HOST` before the namespace boundary
and carries it into both the daemon and attached client. Nested launches preserve
an inherited pin. With no pin, existing CLI behavior and lifecycle hashes remain
unchanged. Explicit invalid pins refuse rather than falling back to a display
hostname. The pin is attribution, not authentication or an access grant; it must
be captured from the normal host launcher, never set to a desired agent name.

A namespace wrapper must run after this capture. If a service manager wraps the
entire launcher, its reviewed controller must capture and supply the original
physical hostname before entering the namespace. Merely installing this code
inside an already-renamed namespace cannot recover the original hostname.
Explicit `QUIPU_HOST` declarations retain their existing precedence. Fleet
routing and governor census continue to use the declared deployment host.

This prerequisite does not enable or launch a namespace. Before a one-card pilot,
qualify the actual service-manager permissions and inherited environment using
the normal reviewed launch path. A systemd user unit's `ProtectHostname=yes:NAME`
implicitly enables a user namespace; kernel support alone does not prove local
security policy permits it. Preserve native UID/process/socket peer checks and
refuse an unsupported mechanism rather than changing host policy or broadening
privilege. See [systemd's execution contract](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#ProtectHostname=).

Before wider adoption, record all of the following on the actual pilot:

- Kernel display hostname is the intended card name; original physical pin,
  deployment host, Quipu read/write headers, governor census/telemetry and inbox
  routing retain their original host identities.
- The existing lifecycle head, receipt and replay fences remain valid; unrelated
  hosts and cards remain distinct.
- Native process and socket peer proof remains valid with the actual namespace
  and UID mappings. No shared runtime home or provider-state edits are needed.
- The intended phone app shows the card name, opens its existing session,
  reconnects with retained identity/pairing, and receives authorized harmless
  steering. CLI connected status alone does not prove this.

Rollback removes the namespace wrapper through the normal launch path while
preserving runtime homes, pairing and sessions. Source review and fixture tests
alone do not authorize a live restart or satisfy these acceptance conditions.

[Before/after fixture recording](demos/physical-host-identity/caption.md).
