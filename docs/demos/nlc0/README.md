# Busy Codex footer replay (aegis-nlc0)

At base 6fc8c2ff, a confirmed Codex frame containing a typed composer and the
current `tab to queue message` footer, with `Working` offscreen, selects Enter.
The regression test `test_busy_footer_queues_when_working_marker_is_offscreen`
fails with `['Enter'] != ['Tab']`. The repaired test selects Tab and preserves
queued/unverified custody. This is an isolated transport replay, not a live
message injection or installed acceptance.

Reproduce with:

```sh
python3 -m pytest -q tests/test_codex_submission.py -k 'busy_footer or queue_hint'
```

The quote-in-body, historical footer and missing composer/footer controls
refuse to treat ordinary text as a current queue hint. The retry control types
one body and sends Enter then Tab after observing fresh footer evidence.

A read-only live Harding capture showed both a stranded typed message and this
footer on November 22. Its initial submission frame was not retained, so this
branch explains a demonstrated failure mode; attribution of all four reported
incidents remains inferred.
