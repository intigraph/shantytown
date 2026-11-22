# Protected inherited controller listener

`recruit_receiver.launch_once` is an unwired library function. A separately
authorized installer must supply a nonblocking Unix stream listening socket.
The function neither creates nor installs a listener, changes its flags, chooses
an endpoint, nor starts a service. Runtime activation remains separately gated.

The existing controller authority check and default-OFF launch gate precede
descriptor or socket access. The protected endpoint descriptor supplies the
controller UID and socket address; the binding supplies recruiter identity,
host and root. The current controller UID, listening address, socket kind,
root-owned parent chain, group and `0660` socket mode must agree. Binding,
descriptor and pathname metadata are rechecked after accepting one connection.
Pathname checks do not claim that a filesystem inode identifies a socket FD;
the inherited listener must come from the trusted installer.

One budget of at most five seconds covers admission, accept and the existing
connected-channel handler. Accept is nonblocking and never retried. Only the
accepted connection is closed; the caller retains the listener. The connected
handler independently verifies real peer credentials, signature, custody,
expiry, nonce and native launch gates. Merge requests remain excluded. A lost
or late launch reply retains durable attempt state and never authorizes retry.

Tests use real Unix sockets, signatures and persistent state with synthetic
protected enrollment and job launch. They do not install a host UID, root socket,
key, identity file or live recruiter. Source rollback is a normal revert while
preserving nonce and attempt records.
