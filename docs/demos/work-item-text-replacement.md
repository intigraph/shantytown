# Explicit work-item text replacement

The same controlled Seeds-transport fixture starts with nonempty notes and a
closed-gate marker. The requested file preserves the evidence and replaces the
marker with historical prose. Before this change, even an explicit replacement
request reaches the protected transport without its replacement flag and fails
with `RuntimeError`; the notes remain unchanged. Afterward, the explicit request
returns `verified`, the exact file body reads back, and there is one write.

```sh
st work item show ITEM
st work item update ITEM --notes-file reviewed-notes.txt --replace-text
st work item show ITEM
```

Without `--replace-text`, a different nonempty body is refused before writing.
Empty-field and identical-body controls succeed without a transport override.
Dry runs write nothing. Timeout-after-commit and lost-readback controls make one
attempt and remain unproven; they never retry automatically.

The tests also exercise real disposable br and Seeds stores, including a
trailing newline. They do not establish production installation or justify
retrying an earlier uncertain write. The field must be read back and its
preserved evidence reviewed before a new explicit replacement.
