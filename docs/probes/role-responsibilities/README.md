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

## Total transport deadline repair

The same local HTTP fixtures compare reviewed head `132f38aa` with repaired
implementation `54265f6bbc654dae7069867a24ae7940d581c384` (including the main
refresh). The role CLI demonstration above was also revalidated after refresh.

With a 0.2-second budget, the old slow-progress response was accepted after
0.436 seconds; the repaired reader timed out after 0.202 seconds. Ordinary
responses succeeded on both versions, and stalled responses timed out on both.
The new paired tests also reject slow headers and verify child cleanup.

[Recorded deadline comparison](deadline-recording.txt) and
[original timing](deadline-timing.log) contain six actual fixture results.
Execution passed the HOME-escape guard. Only the recording command header's
private paths are redacted; output and timing are unchanged. Replay locally:

```sh
scriptreplay --timing deadline-timing.log --typescript deadline-recording.txt
```

To reproduce, extract reviewed head `132f38aa` into a separate checkout, then
run from the candidate checkout:

```sh
python docs/probes/role-responsibilities/deadline_demo.py /path/to/before-checkout
```

These are loopback fixtures with synthetic headers, not production timing or
installed acceptance. Playback requires a terminal, not a browser embed.
