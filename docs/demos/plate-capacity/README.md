# Fresh capacity and P0 overflow

The [recording archive](terminal-recording.zip) and [readable transcript](output.txt) record the same
[probe](demo.py) on base `188938041424e9dff3a233580e7742ad1de2bf7a` and this
candidate's source. These are temporary file-backed items and an injected
owner-reader fixture, not a production board or a live dispatch.

Watch the frozen crew count remain 10 while current owner membership is 7:
ordinary admission changes from refused to admitted. At a genuinely full queue,
ordinary refusal now names the counted IDs, while a P0 obtains its owner and an
overflow admission record. Closing seven inbox messages correctly leaves the
count at ten on both versions. The final candidate count is eight rather than
seven because its P0 successfully took one additional slot before the three
work repools.

From the repository root, with `PLATE_BASELINE` pointing to that base checkout:

```sh
bash docs/demos/plate-capacity/record.sh
scriptreplay --log-out docs/demos/plate-capacity/terminal.log \
  --log-timing docs/demos/plate-capacity/terminal.time
```

Extract `terminal.log` and `terminal.time` from the archive before replaying
(adjust the paths above to the extraction directory). Replay was checked with
`scriptreplay`; the archive preserves both original files byte-for-byte. The
readable transcript only normalizes CRLF to LF. Inline playback is not claimed.
The small recording stays beside its probe in this repository. It
proves source behavior and does not identify the cause of any historical live
refusal, establish installed adoption, or certify cross-host atomic admission.
