# Context handoff

Target: first context hint to the new session's first working tool in under
three minutes. A request, clear, or submitted prompt alone is not that result.
Leave an active operation safe and stop or await your own background tasks.
Keep lifecycle, loss, governor, identity and operator holds intact.

Fill this short checkpoint in a private file. Use pointers rather than copying
logs or session history; write `none` or `UNKNOWN` when appropriate.

```text
<item>: <current state and exact next action>
Landed: <commit/PR and verified state; distinguish installed/running>
Local: <worktree, branch, dirty/unpublished work and evidence paths>
Decisions: <decided constraints and holds; no invented authority>
Next: <one exact command/action and its success check>
Rollback: <reversal or recovery; owned background tasks; pending outcomes>
```

Request the handoff in one call; `--checkpoint-file` posts the file to the item.
Do not also run a separate item-comment command for the same checkpoint.

```sh
st agent cycle --self --checkpoint-file <notes> --checkpoint-bead <id> --quipu-node <existing-node>
```

Use an existing graph node you verified, or the documented
`--no-graph-context '<why unavailable>'` option when no graph context applies.
End the turn once the request is accepted. Do not replace a pending request
merely because it has not run yet; read its refusal and preserve it. Do not use
`/clear` or discard local work to bypass a refusal.

Measure each leg separately: first hint, checkpoint tool start/completion,
request acceptance, cycle execution, fresh session startup, and first working
tool. Retried requests belong to the same episode, not separate successful
cycles. Unknown endpoints stay unknown. Keep host and session identity with
measurements so samples from different machines cannot be conflated.
