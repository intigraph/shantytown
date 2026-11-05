# Context threshold demonstration

Synthetic administrator Stop-hook input on base `5d5d967` and the candidate
implementation in this directory's commit. Both receive 500 and 750 tokens in a
1000-token declared window, with default thresholds and no Jev command.

Before: 50% is silent; 75% is advisory. After: 50% asks for checkpoint and cycle,
explicitly reporting missing Jev; 75% requires handoff with no override.

Replay the recorded terminal output (download both files into one directory):

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

[Readable output](output.log) · [Timing](timing.log) · [Reproducer](demo.py)

Repeat from repository root:

```sh
python3 docs/demos/context-threshold/demo.py 5d5d967
```

This records fixture behavior, not live deployment, Jev service availability,
or a real handoff. Small sanitized logs are retained here with the example.
