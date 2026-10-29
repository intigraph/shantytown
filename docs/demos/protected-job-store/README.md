# Protected own-job metadata fixture

One immutable slot manifest prepares only its own public card and disabled
admission policy. An identical retry is unchanged; an unexpected file refuses
without deletion or adoption. The fixture substitutes the root/inventory trust
anchors inside a temporary directory. It never switches a Unix identity, creates
an account, enrolls credentials, invokes sudo or launches a harness.

Run `python3 -I docs/demos/protected-job-store/run.py --source .`. To compare the
same probe with a base checkout, point `--source` at that checkout. Base
`36451f89735912fa9ecd78cf06242df355da513d` has no metadata preparation component;
implementation `f989bdd51a69ac1566c743b82eebaa895ca61fe0` adds it. Later documentation
commits retain that implementation. This is source-fixture behavior, not native
isolation or installed acceptance.

The retained [output](output.txt) and [timing](timing.txt) are a real terminal
recording, captured with util-linux `script` under the HOME/resource guard.
Replay the downloaded pair with `scriptreplay --log-out output.txt --log-timing
timing.txt`; the output is also a readable transcript. Playback was checked with
the local terminal replay tool; this is not an inline video. These small sanitized
text artifacts are retained here with the source, following the existing demos
directory convention. The [capture driver](capture.py) runs the same probe against
`demo-base` (an archive of the base revision above) and the candidate checkout.
