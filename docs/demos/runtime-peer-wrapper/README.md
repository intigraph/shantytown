# Runtime replacement peer wrapper

The actual wrapper on base `8f792ab7fadc9185b0737051b97b4c15a8edfc41`
raises `NameError(fleet_mod)` whenever a peer census is required. The candidate
`b741df8a8d847924d4d96e89b2d505bc74615a5d` imports that module in the wrapper.
The later main merge retains the same wrapper implementation.

Run `python3 scripts/demo-runtime-peer-wrapper.py` from the source checkout.
The recording invokes the actual base and candidate wrapper with the same four
private fixture inputs. Watch the current peer admit one checkpointed process
replacement request; an unknown peer, an unverified peer replacement, and an
unreachable admission owner all withhold the request. The base raises the
observed exception in the three cases that require collecting peers.

This is candidate source evidence. Admission and peer observations are injected;
there is no network, credential rendering, pane input, or live process cycle.
Installed acceptance still requires the normal scheduled sweep and exact-session
version receipt.

Download [output.log](output.log) and [timing.log](timing.log), then replay:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback and the raw transcript were inspected. These small sanitized recording
files are retained in the repository. No browser embed is claimed.
