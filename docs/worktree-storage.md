# Mounted storage for new worktrees

By default, project worktrees retain the adjacent `<repository>-wt/<agent>`
layout. An operator can opt new worktrees into a separate mounted filesystem
with `SHANTY_WORKTREE_ROOT` and `SHANTY_WORKTREE_MOUNT`, or the configuration
file `$XDG_CONFIG_HOME/shantytown/worktree-storage.json` (default
`~/.config/shantytown/worktree-storage.json`):

```json
{"schema": 1, "root": "/mnt/work/worktrees", "mount": "/mnt/work"}
```

Both environment variables are required when either is present. An explicit
invalid choice refuses provisioning; it never falls back to the root disk.
The mount must be a separate filesystem and the storage root must remain on it.
Admission does not create directories. New container names include the full
SHA-256 of the resolved source path, distinguishing same-named source checkouts.
This digest is a local filesystem namespace, not an authentication identity.

Existing adjacent worktrees take precedence. Git registration keeps an existing
external worktree reachable from its source even after configuration changes;
an unavailable registered external tree refuses duplicate provisioning. Creation,
lookup and cleanup use the same destination resolver. Enumeration includes the
configured storage root as well as the two existing source roots.

Keep the storage configuration while external trees exist: enumeration depends
on that root. To stop creating external trees without hiding them, first finish
or relocate them through the existing guarded worktree lifecycle, then remove
the configuration. This option moves no existing data, changes no active session
and installs no mount. Host-managed configuration must follow normal installation,
mount verification and rollback procedures. Source tests do not establish host
activation or disk relief.
