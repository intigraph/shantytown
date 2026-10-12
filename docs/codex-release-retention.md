# Codex release retention

Legacy role homes retain standalone runtime packages as well as credentials,
configuration, sessions and SQLite state. This tool only handles validated
release payload directories. It never truncates sessions, history, state,
credentials, logs, caches or temporary directories.

Create a read-only plan from the reviewed installed source:

```sh
python -m shantytown.codex_retention --root /path/to/deployment-root \
  --role worker --keep-previous 2 > worker-plan.json
```

The default keeps the selected current release, the newest release the launch
resolver could select, every same-user release referenced by an executable,
memory mapping or open file, and two previous versions before each retained
anchor. Fresh payloads younger than one day are also retained. Set
`--keep-previous N` to choose zero through twenty previous versions.

Review the exact plan, then execute through the same tool:

```sh
python -m shantytown.codex_retention --root /path/to/deployment-root \
  --role worker --keep-previous 2 --execute-plan worker-plan.json
```

Execution refuses changed inventory, pointers or reader visibility. It holds a
cleanup lock, rechecks before each removal, detaches each eligible directory
atomically, and restores it if a reader appears before removal. Unknown custody,
unsupported layouts, external links and unsafe removal support refuse.
Payloads with hardlinks contribute zero estimated freed bytes for those files.

This is a same-user operational guard, not a security boundary against another
writer using the same account. Run it only during an owner-coordinated maintenance
window with no updater or direct launches of obsolete binaries. The cleanup lock
coordinates this tool; it does not claim an upstream updater lock. Other-user
payload readers are outside the contract. Keep all runtime/state files if that
custody condition cannot be established.

The command is agent-invoked: no launch hook, reaper or timer is installed. Review
and merge the source first, then use an explicit reviewed plan. A source merge
does not reclaim space. Noncritical source landing follows the repository's
release hold. Record before/after release counts and allocated bytes and verify
the retained executable and untouched state through the same probes.

[Official configuration documentation](https://learn.chatgpt.com/docs/config-file/config-advanced#config-and-state-locations)
confirms that Codex home also contains credentials, history and other state.
The release layout and this cleanup contract are validated locally; this is not
an upstream package-cleanup API.

## Isolated demonstration

Run `PYTHONPATH=. python examples/codex_retention_demo.py`. Five fixture release
directories become three (current plus two previous); a newly observed reader
refuses the saved plan, and session bytes and timestamps remain unchanged.
No installed home or real process custody is used by this fixture.

The retained [terminal output](demos/codex-release-retention.txt) and
[timing](demos/codex-release-retention.timing) can be replayed with
`scriptreplay --log-out docs/demos/codex-release-retention.txt --log-timing docs/demos/codex-release-retention.timing`.
Playback was checked locally; this is a terminal recording, not an inline video.
