# Startup stack orientation

The same offline identity/plate fixture renders no stack or Camayoc orientation
on base `a2afbdf4660908757245f349b826d5707c6e22f9`. Source candidate
`a98913f8021b599aaa7644b62192d06b786286a2` adds the shared packaged section on both successful
and unreadable anchors. The packaged primer's Camayoc/cy whole-word count goes
from 0 to 6. Watch `stack-prime/1`, the Camayoc skill and `map_question` change
from false to true while identity/plate or the unreadable warning remains.

[Terminal recording](output.log) and [timing](timing.log) are retained here as
small repository artifacts. Download both and replay with util-linux:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was verified locally. This is a replayable terminal recording; the
[normalized transcript](transcript.txt) provides readable output. Raw CRLF bytes
are preserved in the plain-text recording so replay timing stays exact. Reproduce from the repo root:

```sh
python3 docs/demos/stack-primer/probe.py --base a2afbdf4660908757245f349b826d5707c6e22f9
```

The recording includes hashes of all three runtime inputs. The demo invokes
the real shared startup renderer with local mocked plate, deployment-rule and
crew-memory reads. No live launch, service query, tool provisioning or memory
write occurs. Hook and verified launch delivery are covered by the focused
tests; installed behavior on another host remains a separate acceptance step.
