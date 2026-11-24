# Separate attended custody admission

The same local probe runs against bridge revision
`7731c3ccf25d04a59198fcde00291281aad4cb20` and attended-contract source
`e5c03b9e017e9613fedca8eac7cbcaa2bc59561f`, rebased without code changes as
`e89431bbaaf292869bdc2f9c02ec6c808d4ebb67` onto the landed bridge. Before:
no separately configured attended custody
admission. After: an explicit current UID and private 0700 directories admit;
a different UID and a group-writable intent directory each refuse.

[Output recording](output.log.gz) and [timing](timing.txt) preserve actual
util-linux `script` output. Download, decompress and replay with
`scriptreplay --log-out output.log --log-timing timing.txt`. This is a terminal
recording, with no inline player. The raw recording was inspected for private
paths. It demonstrates source directory admission only; no forge call, queue
entry or installed-runtime acceptance is represented.

To repeat, set `BEFORE_SRC` and `AFTER_SRC` to those source checkouts,
`DEMO_PARENT` to an existing private directory with non-writable ancestry,
and `PYTHON` to a Python environment with the project's dependencies. Run
`sh run.sh` from this directory. The probe creates and removes isolated child
fixtures; it changes no shared tree or production enrollment.
