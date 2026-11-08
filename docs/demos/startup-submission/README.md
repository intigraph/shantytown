# Startup submission boundary

This library fixture holds process liveness and hook verification constant and
varies startup delivery. On base `6bb4694988539c60fbc1a4060a9ecb75fe9c8bcf`,
a failed startup returns 0. On this candidate it returns 2. The successful
control returns 0 on both. All runtime, pane and tracker ports are inert;
this is source behavior, not an installed launch or a reproduction of the
intermittent terminal paste race.

Run `python3 docs/demos/startup-submission/demo.py` from this checkout.
The small [output recording](demo.output) and [timing file](demo.timing) are
retained with the source. Replay after downloading both:

```sh
scriptreplay --log-out demo.output --log-timing demo.timing
```

Playback was checked with util-linux scriptreplay. These files are a terminal
recording, not a video embed. The recording applies to this branch's launch
boundary; exact submission-receipt and unread-pointer controls are in
`tests/test_new.py`. It does not establish why the incident's input stranded.
