# Native tool-call trace outcomes

Native shell hooks can report tool transport completion without reporting the
process exit code. That completion is insufficient evidence of process success.
The statistics hook therefore observes native transcript call/output pairs by
the transcript's exact call ID and records an UNKNOWN process outcome.

The trace explicitly names its granularity as `tool-call`: a code execution cell
can contain several nested commands. Its transcript call ID must not be confused
with a nested shell hook's execution ID. The recorder never joins those IDs by
command text, time or agent, and never parses output text as exit status.

A new recorder adopts the current transcript boundary rather than attributing
historical calls to the current task. Run the normal task-boundary declaration
before measuring new controls. Later actions use only the latest confirmed task
binding for that same session and agent; an unconfirmed new binding is UNKNOWN.
A completion inherits its action's binding even after the next task begins.

The session metadata must match the hook session. Partial output records wait
for completion, and orphan outputs cannot manufacture an action. The observer
runs on pre/post/failure/stop capture, so a final output can be observed at stop.
Source content, commands and output are omitted from the trace. Normal statistics,
policy and tool outcomes continue even when trace observation is unavailable.

The local journal claims each emission before appending it. An interrupted append
is an indeterminate attempt and is not blindly resent. Its outcome stays pending
until the action's delivery is confirmed; a database row alone is not proof that
an event reached the spool. Review attempted/pending rows when diagnosing gaps.

This workaround adds observations. It grants no permission and changes no
policy enforcement mode. Typed process status from a corrected native bridge
requires separate source review and native acceptance before adoption.
