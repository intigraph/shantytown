# Closed deferrals stay quiet

Before this change, a closed item retaining an expired `defer_until` and
`resume_when` could still generate an OWNER-PACING reminder or administrator
fallback. Six new controls failed against the original producer: two delivery
arms and four historical-gate arms.

The producer now removes `closed` and `done` rows before planning gate reads.
The same six controls pass, alongside the existing open/deferred, routing,
prose-gate and forge-event tests (201 tests total). The delivery controls also
reopen the row and verify that its still-lapsed gate prompts its owner again.
No item metadata, deferral authority, or resume gate is changed.

The [recorded output](output.log) demonstrates the two end-to-end delivery and
reopening controls. Replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Reproduce the demonstration with:

```sh
python3 -m pytest -q tests/test_deferral_owner_pacing.py -k terminal_item
```

This is private-fixture source behavior. Normal installation and a scheduled
producer observation remain separate acceptance evidence.
