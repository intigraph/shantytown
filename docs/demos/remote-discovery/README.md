# Status-only remote discovery

Two synthetic agent cards advertise the same provider server name. Watch the
[recording](output.log): the base offers no local disambiguation; the candidate
adds distinct local labels, marks the collision and says phone visibility is
unverified. Provider server names remain unchanged.

This records actual source behavior with a synthetic status-only provider, not
an installed daemon or a phone. Base:
`0ed92183c61e3dfad8f94e8b3da5abbc8dd82c4a`; candidate source:
`d26d0a277c8cb990a87c8533ba8646510c545282`. Later demo-only commits preserve that
source. The provider rejects every RPC except `remoteControl/status/read`.

Repeat from this checkout with Python 3.11 or newer:

```sh
python docs/demos/remote-discovery/reproduce.py
```

Download `output.log` and [timing.log](timing.log) together and replay with
util-linux `scriptreplay --timing timing.log --log-out output.log`. Replay was
checked. The small sanitized recording is retained here with the source.

This does not demonstrate phone pairing, vendor naming support, daemon startup,
macOS process identity or mobile visibility. Those acceptance limits remain open.
