# Preserve the Codex PATH link on unchanged launches

The same emitted launch setup runs against private fixtures on base
`fd30ffc9024a9730875a88ec0abff09fcaf07f46` and this candidate. It invokes a
private executable stand-in, never an agent or the real HOME link. Before,
an unchanged target rewrites link timestamps; after, inode, mtime and ctime
remain unchanged. Both versions still repair a changed target.

Run from the repository root:

```sh
python3 docs/demos/codex-shim/demo.py
scriptreplay --log-out docs/demos/codex-shim/output.log --log-timing docs/demos/codex-shim/timing.log
```

[Recorded output](output.log) and [replay timing](timing.log) are retained with
this source demonstration. The terminal replay requires downloading both files;
inline playback is not claimed. This proves candidate source behavior, not
normal installation or a production crew launch. Rollback is a normal revert.
