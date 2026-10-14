# Publish an explicit linked worktree

An explicit extra worktree previously went through the canonical provisioning
map. If the old canonical tree was on a different branch, the push refused even
though `--source-branch` matched the extra tree being named.

The resolver now verifies the literal path against Git's registered worktree
roots, its top level and separate git/common directories. A malformed gitfile
or an unregistered copied marker refuses. Shared checkout paths and bare names
continue to select the canonical agent worktree.

```sh
st repo push /path/to/project-wt/worker-topic worker \
  --source-branch worker/topic --branch worker/topic
```

The full-command demonstration uses two disposable trusted bare peers and an
extra linked tree. Before: the command refuses on the old canonical branch.
After: both peers receive exactly the extra topic HEAD, while their main refs
and the old tree's branch, HEAD, dirty contents, index and configuration remain
unchanged. Caller/source mismatches and an untrusted peer still refuse before
any peer is contacted. This preserves explicit destination intent and normal
hooks; it grants no merge or deployment authority.

The focused push suite passes 41 controls. Its two long timeout controls are
unchanged and excluded from this focused run; the complete CI matrix remains
required. Source fixtures and a read-only source resolver probe do not establish
installation. Repeat the same installed resolver probe after normal projection;
the originally refused real publication remains an owner action.
