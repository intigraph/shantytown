# Condition-status batch demo

The same frozen offline corpus contains 436 candidates and 59 distinct closed-condition targets. The retained serial reader makes 59 queries; the candidate batch reader makes 3. Verdicts and every finding remain identical, including missing, shadowed and unsupported-status UNKNOWN controls. The serial reader is unchanged from base a69a19e45417e4388dce11766c96e098ff36cc76. The new reader is demonstrated from the commit containing this directory.

Run `PYTHONPATH=. python3 docs/probes/pr-demos/condition-batches/reproduce.py`. The service is mocked and time frozen: this establishes fixture parity, not live findings, a full-pass query count or deployment. Fresh full detail, single-condition reread, mutation and readback remain separate barriers.

[Terminal recording](demo.cast) uses asciinema v2; download and replay with `asciinema play demo.cast`. [Transcript](transcript.txt) supplies the same actual output without a player. Recording timestamps come from actual subprocess output; no inline playback is claimed. The small sanitized recording is retained with the repository's existing PR-demo artifacts.
