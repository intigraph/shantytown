# Private Seeds launcher demonstration

Target: private source binaries, an injected inert provider, and a loopback HTTP fixture. No installed program, real secret store, or production authentication is exercised.

Before native source: `fd518dd2c00ca7aa1213e59a830dac803fca8403` (the reviewed descriptor primitive). This retained private binary was built at that source commit, not rebuilt from the squash merge. It refuses the new admission flag, with **0 provider calls and 0 HTTP requests**. After native source: `0414404a36bc5a9a46b4dc04d61fa69fedc0c7f3`. Adapter/test source: `9567551ed31e57c79ec464de5a97feffaa6988d3`; the later caption-only commit leaves those source blobs unchanged.

Watch the measured output: a selected command fetches once, sends one own fixture bearer and zero foreign bearers; changing the destination after admission refuses before HTTP; the next explicitly deselected command uses the native shared fixture default with no provider call. The repeated fixture runs both a URN and a canonical-shaped HTTPS IRI, mapped to a stable native-safe SHA256 declaration without changing the provider reference. Those declarations are not authentication claims. It also supplies legacy Seeds/Quipu aliases and verifies they are removed only from the child. It checks that a server error echoing the selected bearer is redacted while the original failure status is preserved. The fixture refuses writes with HTTP403; observed headers are not production authenticated-principal receipts. Additional trust/transport, malformed proof, provider refusal, rotation and descriptor cleanup controls are in the tests.

The output-only [recording](seeds-launcher-demo.log) and [timing](seeds-launcher-demo.timing) were captured together with util-linux `script`, replayed, and inspected as raw bytes. They contain no bearer bytes or internal paths/hosts. Download both to replay; inline playback is not claimed:

```sh
scriptreplay --log-out seeds-launcher-demo.log --log-timing seeds-launcher-demo.timing
```

Repeat with private copies of those native revisions:

```sh
SEEDS_ADAPTER_TEST_BINARY=/path/to/new/sd SEEDS_ADAPTER_LEGACY_BINARY=/path/to/old/sd python3 -m pytest -q -s tests/test_seeds_credentials_cli.py
```

The small sanitized recording is retained in Git with this caption. Source review, normal artifact delivery, installed identity, authenticated CLI/SDK receipts and activation remain separate gates.
