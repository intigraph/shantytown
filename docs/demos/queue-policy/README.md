# Ranked intake before and after

The same synthetic `st task` request creates an unlaned, unranked item on base
`2e85dd14`; implementation `45e1053afc11adb54a563fa6667fc5c73325f546`
creates it in Next at rank 1 and prints the observed queue position. The full
Next control refuses with zero writes. `SHANTY_QUEUE_POLICY=enforce` is explicit
in both runs; the baseline ignores the setting because it lacks this behavior.

[intake.cast](intake.cast) is an Asciicast v2 recording with three actual output
frames. Its JSON/frame structure was verified. A terminal playback program was
not installed in the recording environment; browser embedding was not tested.
The deterministic command can be rerun without a player:

```sh
python3 docs/demos/queue-policy/reproduce.py --source .
python3 docs/demos/queue-policy/reproduce.py --source . --full
```

For the before case, pass a clean checkout of base `2e85dd14` as `--source`.
The script replaces only the tracker with an in-memory fixture and calls the
actual CLI. It never contacts a production tracker, opens a pane or writes a
real queue. Both the recording command and focused controls finished with the
HOME/resource guard clean. This proves source behavior, not installed policy
activation, a duration estimate, or the separate Rikuy producer/display path.
