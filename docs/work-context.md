# Exact work-item context

Before searching for related history, read a known work-item ID:

```sh
st-context example-123
```

Use `--root /path/to/crew` to select an existing deployment explicitly. The
command otherwise uses the same root discovery, deployment configuration,
tracker selection and store proof as `st`. It does not select an alternate
store when the configured reader fails.

The output includes item state, blockers, resume notes, recent comments,
linked rulings and recent evidence. Evidence retains its record link and
source attribution. Missing attribution and failed reads are UNKNOWN. An
empty exact section names the subject it checked; it does not establish that
the graph contains no relevant history.

Then use `quipu_search` for related history. A semantic NO CONTEXT result does
not erase the exact evidence. This command does not change search admission
or the similarity floor.

For a source checkout, run `python -m shantytown.work_context_command` with
the same arguments. The query-first session directive names `st-context`;
the command does not run automatically inside metadata capture or task-order
recording. Installing the new console entry point requires the normal package
update. Source tests alone do not establish installed hook behavior.
