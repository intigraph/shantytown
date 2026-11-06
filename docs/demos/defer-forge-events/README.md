# Deferrals bound to a pull request

The same `pr-merged:github/owner/repo#7` marker is untestable on base
`f9941a35a914ec925a8d2226aade3dcb79b124b8` and testable on feature head
`c2ac41433f1d06ecac8d7f8a241fd873d9b88ce3`. The actual evaluator then rejects
an open PR, accepts a matching merged PR, and leaves a foreign receipt UNKNOWN.

[Recorded output](output.log) and [timing](timing.log) are a terminal recording,
not a video or a verified inline embed. Download both files and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Repeat the library demonstration from a checkout containing the base commit:

```sh
python3 docs/demos/defer-forge-events/demo.py
```

The forge responses are private fixtures. This demonstrates parsing and evidence
evaluation, not deployment, a live deferral, or a crew launch. The guarded
integration tests separately exercise the actual defer writer and scheduled
sweep. The recording and caption are retained with the source in this directory.
