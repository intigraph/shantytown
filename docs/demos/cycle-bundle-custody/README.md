# Exact-ref bundle custody demonstration

The same tiny committed Git fixture is refused by base
`09c1c6a70d298dbe8cf254777e9063040e489211` and accepted by the candidate only
after exact independent verification and root acceptance. Wrong SHA256 and
tracked dirt still refuse. This is policy/source evidence: it never cycles an
agent, contacts a tracker, publishes a ref or changes an installed service.
Item comments and crew cards are explicitly synthetic; Git bundle checks are real.
The candidate's executing source bytes are bound by [source hashes](source-sha256.json).
The PR identifies the candidate commit containing those bytes.

[Recorded terminal output](output.log) and [timing](timing.log) form a util-linux
terminal recording; download both and use:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was checked locally. No inline video player is promised. The log is
also the readable transcript. This small synthetic recording is retained in the
repository with the source. To repeat from a checkout with the retained base
object available:

```sh
PYTHONPATH=. python3 docs/demos/cycle-bundle-custody/demo.py
```

Repeat meaningful checks through your normal HOME-escape guard. The demonstration
is not full-archive recovery rehearsal, a real root grant, current CI, peer
approval or installed acceptance. See the [custody contract](../../guides/cycle-bundle-custody.md).
