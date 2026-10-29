# Preview the crew before launching

The 24-second recording runs the real `st fleet init --dry-run` command twice, first with a coordinator alone and then with a builder. The root is an absent relative `.shanty` inside a private fixture workspace. No cards, settings, work tracker, sessions, timer or permission changes are written. The explicit files backend belongs only to this non-writing preview; it does not change an existing crew’s tracker.

Recorded with `st 0.8.0`; the manifest records `--version` and the executable entrypoint digest. Use the same version to reproduce the preview. The names coordinator/builder are public fixture names, not runtime identities.

With a verified Shantytown installation, prepare a new, absent workspace:

```sh
mkdir /tmp/shantytown-demo
touch /tmp/shantytown-demo/.terminal-demo-sandbox
python3 docs/demos/terminal/render.py docs/demos/terminal/demo.tape.json \
  --workspace /tmp/shantytown-demo --tool st="$(command -v st)" \
  --output /tmp/shantytown-render
```

The shared recorder isolates HOME and XDG paths. The `.shanty` directory must still be absent after recording; the preview is not an actual crew launch or permission grant. It preserves the program’s full native output. Read `terminal/transcript.txt` for a static alternative.

The recorder is unchanged from Tambo’s canonical `stack-terminal-24` harness at `b0765b5d8f16a6a26acb3595552f17826d965b44`, SHA-256 `bebbe000565314f18a58731f2a1a4690577db127b3673fa10a45ce74eef0f23c`. Reading holds are deliberate; actual command durations are in the manifest.
