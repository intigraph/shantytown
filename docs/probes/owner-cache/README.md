# Owner candidate cache across unrelated commits

Four owner reads on the same 30-item private SQLite fixture return identical
items before and after unrelated description writes. The recorded candidate is
based on `78c1ab1864d6e819e11dbaf8132a856327454d7a`. Its query bytes are unchanged;
the BEFORE arm disables only the new candidate-retention context, preserving the
existing cache and change-feed checks. AFTER enables the candidate context.

| Four calls | Query requests | Store-held milliseconds |
| --- | ---: | ---: |
| Before | 8 | 32.91 |
| After | 3 | 7.73 |

Query requests per owner call fall from 2 to 0.75; measured store-held time per
owner call falls from 8.23 to 1.93 ms. Watermark and change-feed requests remain
necessary and are not counted as query requests. This is a small synthetic
fixture on an installed 0.17.0 loopback server, not a production benchmark or
proof that a historical production query digest disappeared. No network model
acquisition, production read or deployment is involved.

The recorded implementation bytes (SHA-256):

- `shantytown/seeds_plate.py`: `6a83eddc91c1eb294e6b3ce6587c06ad2c7ea185166097369472a267b0e476cf`
- `shantytown/seeds_read_cache.py`: `2e0fd43165d562de2e92d1317a893931355006077df3b4087342ec6b182b6c54`

[Recording](output.cast) is an asciinema v2 terminal recording converted from
the original util-linux output and timing, preserving every output byte and
frame delay. It is not a video or an inline player. Download and replay:

```sh
asciinema play output.cast
```

Repeat from this source checkout with installed `quipu` and `quipu-server`:

```sh
python3 docs/probes/owner-cache/probe.py --fixture-root /tmp/owner-cache-new
```

The conversion was byte-checked against the original output and timing; inline
playback is untested. The JSON recording also provides a readable text fallback.

Use a new private fixture directory. The script refuses an existing database,
binds only loopback, retains its receipt and logs, and terminates its own server.
The unit controls separately require UNKNOWN on membership changes, unavailable
or truncated evidence, and store replacement; selected field changes reload the
changed fields. The before/after measurement does not substitute for those
negative controls or for installed acceptance.
