# Inherited session-capture hooks

The graph-capture skill's supported installer owns the canonical executable
`~/.gt/hooks/quipu-session-capture.sh` and its registrations. Provisioning checks
existing Stop registrations before projecting a workspace; it does not install
or register another solicitor.

An active registration must point to an executable, regular, non-symlink
canonical file whose SHA-256 matches `hooks/quipu-session-capture.sh` in the
manifest's declared `graph-capture` skill source. Without a manifest, the local
`skills/graph-capture` source is authoritative. Missing sources, stale bytes and
unverifiable registrations refuse provisioning. Use that skill's supported
`install-graph-capture-hook.sh --check` and `--install` paths to reconcile, or
explicitly retire the inherited registration. Preserve other hooks and the
installer's once-per-session guard.

Discovery covers the workspace's Claude settings, its shared parent settings,
the matching `<project>__<crew>` managed override, user Claude settings and the
explicit role settings path (JSON or TOML). Other projects' overrides are not
adopted. This is static inspection of conventional canonical path references;
indirect shell programs are not evaluated.

`.shantytown-legacy-session-capture.json` records the source and canonical
hashes and hashes of the checked registration files. It proves the bytes
checked during this invocation, not successful completion of later provisioning
steps, hook execution, or adoption by an already-running session. An inherited
receipt becomes `unregistered` after explicit retirement. No receipt is created
for an unregistered installation. `--instruction-report` remains an instruction
projection report and does not certify hook delivery.

Arming is library-based: every normal workspace provisioning invocation performs
the check. Crew-wide installation and existing-session activation retain their
normal deployment gates.
