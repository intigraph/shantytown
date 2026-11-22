# Protected controller endpoint client

`recruit_endpoint.exchange` is an unwired library entry. It selects one local
Unix socket from the fixed root-owned `/etc/shantytown/recruit-endpoint.json`
policy, then calls the existing bounded signed-request transport. It adds no
listener, CLI route, key delivery, root identity or deployment installer.
Runtime activation remains separately gated; the existing gate defaults OFF.

The closed version-1 descriptor requires `host`, `root`, absolute `socket`,
`socket_gid` and `controller_uid`. Host/root must match the separately protected
recruiter binding. The process UID and request identity must match that binding;
the controller UID must differ. The socket must be root-owned, mode `0660`, with
the declared group and an immutable root-owned parent chain. No request or
environment variable selects these values. Descriptor/binding changes or a socket
replacement between connection and send refuse before any request bytes.

Connection, revalidation and the existing exchange share one budget of at most
five seconds. Peer credentials must match the declared controller UID. A failure
before send refuses without bytes; transport uncertainty after send retains the
caller's original nonce and attempt record, with no retry or polling fallback.
Only review launch/stop envelopes are accepted; merge verbs remain excluded.

The existing controller still verifies the signed envelope, exact native custody,
expiry, nonce and job/launch gates. A socket or response grants no authority.
Source rollback is a normal revert; preserve all existing attempt/audit state.
