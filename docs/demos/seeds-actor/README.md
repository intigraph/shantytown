# Declared actor in child tools

The same isolated probe executes each real Claude, Codex and OpenCode launch
with private harness and `sd` doubles. On base
`9fddefbee23f4d40e06552efefc52ed2f26a4126`, the child inherits `other-card` as
`SEEDS_ACTOR` even though the crew card is `writer`: all three checks fail.
With this change, all three child tools receive `writer` and pass.

[Terminal output](output.log) and [timing](timing.log) are plain-text recording
artifacts. Download both and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Reproduce from the repository root:

```sh
python3 docs/demos/seeds-actor/probe.py --base 9fddefbee23f4d40e06552efefc52ed2f26a4126
```

The probe prints hashes of the actual launch implementations and checks the
expected failing baseline and successful candidate exit codes. Temporary
fixture paths are normalized to `<scratch>` before recording. No tracker
write, real agent launch or credential operation occurs. This proves declared
environment propagation; signing identity and installed Mac acceptance remain
separate controls.
