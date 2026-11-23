# Writer-only bootstrap

Two real Git/FD fixtures show that the read-only normalized-mode proposal changes
no metadata or pin bytes and matches the later actual measurement. A fixed staged
operator proposal then grants the exclusive writer lease and normalization while
consumers continue refusing the absent canonical pin, before and after the write.

Repeat the two named tests in `output.txt`. [Output](output.txt) and
[timing](timing.txt) are retained for download and
`scriptreplay --log-out output.txt --log-timing timing.txt`.

The fixtures model root-owned policy installation. They perform no live pin/ACL
installation, source normalization, activation or job launch. Malformed canonical
and staged policies and a post-normalization mismatch are separate refusal tests.
