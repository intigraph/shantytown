# Explicit intake deadline

The same actual CLI dry run requests a new item without a deadline. At base
`6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf`, the explicit deadline policy is
unsupported and the command accepts the missing deadline. The candidate refuses
it, then accepts an explicit date and prints its normalized UTC value.

[Recorded output](output.log) and [timing](timing.log) retain all three commands.
Each case uses a fresh temporary root, no assignee and `--dry-run`; no tracker
item, crew message, deadline policy or installed program is changed. This is a
CLI source demonstration, not a production intake or deployment measurement.
The separate guarded tests prove native creation receives `--due` in its original
transaction and the files fixture persists the normalized due date.

To repeat, prepare a clean read-only checkout of the base above and run from the
candidate repository root:

```sh
python3 docs/demos/intake-deadline/demo.py --before /path/to/base-checkout
scriptreplay --log-out docs/demos/intake-deadline/output.log \
  --log-timing docs/demos/intake-deadline/timing.log
```

The required-date policy is opt-in and affects `st task`; direct SDK creation
and internal message records remain outside this slice. No seven-day backlog
acceptance, installation or runtime enforcement is implied.
