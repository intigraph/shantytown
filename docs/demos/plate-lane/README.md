# Plate lanes: Now, then Next by rank (aegis-6vto.4)

The same mocked Seeds rows go through the real `SdTracker` plate (`br.plate`)
on base source `5646631bf428` and candidate source `a198065ab00f`:

| Case | Base | Candidate |
|---|---|---|
| P0 unlaned item; two Next items (rank 2 at P3, rank 1 at P4) | `p0-unlaned` | `p4-next-rank1` |
| Add one P4 Now item | `p0-unlaned` | `p4-now` |
| Control: no lanes or ranks anywhere | `p0-unlaned` | `p0-unlaned` |

Priority still orders unlaned and Later items exactly as before. Inside Now and
Next, rank orders (then due, then age), not priority. The tracker process is
mocked; no board or session is changed.

[output.log](output.log) is a plain readable transcript, not a timed recording
(this was recorded on macOS, which has no util-linux `scriptreplay`). To
reproduce, set `LANE_BASE_SOURCE` and `LANE_HEAD_SOURCE` to the two source
checkouts and run `python3 demo.py`. The later commit that adds this directory
changes documentation only.
