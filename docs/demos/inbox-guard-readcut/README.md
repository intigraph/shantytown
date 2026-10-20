# Inbox status-guard read cut

An inbox read checks every owned task for unsupported status before selecting
messages. Previously that check and candidate selection used separate requests.
The candidate response now includes the same status counterexample relation;
any counterexample refuses before field hydration. Other plate and admission
readers retain their existing standalone guard.

[Recording output](output.log) and [timing](timing.log) show the same private RDF
fixtures on base `90ff87992594efa46f58d54bb405c2f979749e22` and functional candidate
`cca2deab51b790c18200d746eaeceac124597d40`:

- Populated: three requests become two, with the same receipt ID.
- Empty: two requests become one, with the same complete empty result.
- An ordinary owned task with an unknown status: both versions refuse; one request.

The measured boundary is `owner_rows(..., messages_only=True)`, not an entire
CLI invocation. Store and native-format admission are unchanged and may add
requests. This is a local RDF fixture, not a production server, traffic census,
installed performance result, or proof of recipient delivery. Separate tests
exercise the composed query against a private native Quipu server.

With the project's test dependencies installed, reproduce from a full clone:

```sh
PYTHONPATH=. python docs/demos/inbox-guard-readcut/probe.py \
  --base 90ff87992594efa46f58d54bb405c2f979749e22 \
  --candidate cca2deab51b790c18200d746eaeceac124597d40
```

Download both recording files and replay with:

```sh
scriptreplay --log-out output.log --log-timing timing.log
```

Playback was checked with util-linux `scriptreplay`. These are small terminal
output/timing files retained with the source, with a readable transcript fallback;
inline video playback is not promised. Candidate source is unchanged by the
recording/caption commit. No live messages, tokens, private board data or
production calls are used.
