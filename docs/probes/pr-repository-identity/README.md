# Renamed repository creation preflight

The old adapter can POST to a renamed repository, then reject the canonical PR
URL with `created: null`. It already exits 2; this is not an exit-zero control.
The candidate checks the canonical slug and stable repository ID first, refusing
an old slug before any POST. It rechecks identity before creation. It never
rewrites a remote or automatically retries an uncertain write.

Run this private fixture from the source checkout:

```sh
python3 docs/probes/pr-repository-identity/demo.py --baseline-ref 8f1d426bf91dd392937d00620739ff24069d634f
```

The fixture substitutes candidate metadata and forge responses; it invokes the
real adapter command, without running an installed CLI or making network calls.
The baseline module is read from the specified Git revision. Unchanged helper
imports come from the candidate checkout; candidate Git discovery is mocked in
both arms. The PR caption identifies the candidate revision, and
[output.json](output.json) records both source digests and actual responses.

Watch the renamed case change from one POST to zero, while canonical creation
still makes exactly one. Null and lost post-write responses remain UNKNOWN with
one attempted POST and no retry. Missing repository identity now refuses before
POST. These are private forge fixtures, not observed live GitHub mutations.

Download [recording.log](recording.log) and [timing.log](timing.log), then replay:

```sh
scriptreplay --log-out recording.log --log-timing timing.log
```

Playback was checked locally. The output log is the readable transcript; an
inline browser player is not assumed. The small recording is retained alongside
the reproducer in this directory.
