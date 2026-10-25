# Role responsibility CLI demonstration

The same isolated crew cards are shown through `st anchor member` and
`st fleet roles show`. Before, neither command displays responsibilities.
After, anchor displays the worker summary, and roles show displays all five
governed role summaries. The local `executive` catalogue entry has no graph
rule and is explicitly UNKNOWN.

This is actual CLI output with local files and deterministic graph-response
fixtures. It demonstrates candidate source behavior, not a deployment or live
role data. No network requests, board changes or notifications are performed.

- Base: `15ddda519e481f70277ce94c0dad826c907d17b4`.
- Implementation: `6fbf410` (subsequent recording files do not change behavior).
- [Recorded terminal output](recording.txt), [original timing](timing.log).
- Recording and replay passed; execution ran under the HOME-escape guard.
  Only the recording header's private checkout path is redacted; CLI output
  bytes and timing are unchanged. The initial unguarded recording is excluded.

Download both recording files, then replay with util-linux `scriptreplay`:

```sh
scriptreplay --timing timing.log --typescript recording.txt
```

To reproduce, extract the base revision into a separate directory, install the
candidate's test dependencies, then run from the candidate checkout:

```sh
python docs/probes/role-responsibilities/reproduce.py /path/to/base-checkout
```

These small artifacts stay in this repository with the probe and caption;
playback requires downloading them and using a terminal, not a browser embed.
The administrator ranking digest is covered by independent fixtures and is not
part of this recording.
