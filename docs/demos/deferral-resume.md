# Mechanical deferral resume demonstration

A marker-only closed deferral previously stayed deferred after its blocker
closed, because the writer's required metadata failed the release check.
An external installed condition also stayed held despite a definite MET.

This recording runs the same private writer/sweeper fixtures on base
`7c1d5d6434d01f04d67bc19fd2c2a85ffabed3e3` and candidate
`3798ec4389c4a349334bafd4a243d3957de6102b`.
Watch the satisfied closed and installed cases change from deferred to open.
The open blocker, UNKNOWN read, prose and human-hold controls stay deferred.

[Readable transcript](deferral-resume.transcript.txt) and
[recording timing](deferral-resume.timing.txt). Download both into one directory:

~~~sh
scriptreplay --log-out deferral-resume.transcript.txt --log-timing deferral-resume.timing.txt
~~~

Playback was checked with util-linux scriptreplay. This is a replayable terminal
recording; no inline video player is claimed. The small files remain in Git.

The fixtures use the actual defer writer, stored file rows, condition evaluator,
fresh-item check and sweeper. Version producer facts are injected; no GitHub
release, production item or installed service is changed. The source demo passed
the HOME/resource guard. Subsequent recording-only changes preserve the
demonstrated runtime source.

Repeat the complete fixture controls from a checkout of the proposal:

~~~sh
python3 -m pytest tests/test_resume_writer_sweeper.py -q
~~~

For the before control, copy that same test file into a separate checkout of the
base above and run it there. The satisfied-condition positives fail on that base.
Source behavior does not establish natural scheduled acceptance after adoption;
that acceptance remains a separate check.
