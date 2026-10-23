# Current refusal: hold and report

The same incident refusal prefix reads `idle` at base `8fdc5f1` and
`safeguard-blocked` at implementation `bf93391`. Two report passes produce one
durable administrator inbox message, zero automatic recovery actions and zero
pane input. Cleared, historical, auth and usage controls do not become safeguard
findings. Current-main integration changes no demonstrated safeguard code.

The [transcript](safeguard-hold.transcript.txt) and [timing file](safeguard-hold.timing.txt)
are an actual private terminal recording under the HOME/resource guard. Download
both and replay with:

```sh
scriptreplay --log-out safeguard-hold.transcript.txt --log-timing safeguard-hold.timing.txt
```

This runs the real triage, tend and report functions with an isolated file inbox
and fake panes. It contacts no provider, tracker or live pane and demonstrates
source behavior; it does not claim installation. The captured prefix is provided
in `tests/fixtures/safeguard-refusal.txt`; request-ID controls use synthetic IDs.
The retained capture after human clearing is a separate negative control.

Repeat the public source controls with:

```sh
python3 -m pytest -q tests/test_safeguard.py
```

A current refusal stays held for human review. There is no automatic context
clearing, retry, cycle, or model switch.
