# Ordinary graph crew-memory transport

Trigger: read the same explicitly selected owner's memory against a transport
that supports ordinary Quipu queries and has no memory service. The actual base
at `935220342d9219d26da493a46f2745f9bd5fecca` requests `/memory/read` and refuses;
the candidate requests `/query` and accepts an explicitly complete empty owner
graph. The populated positive controls exercise two owners, exact UTF-8/CRLF,
atomic concurrent-writer refusal and lost-reply replay in `test_memory_graph.py`.

Repeat from the repository root with test dependencies installed:

```sh
PYTHONPATH=. python docs/demos/ordinary-crew-memory/probe.py
```

[Transcript](transcript.txt) is actual captured stdout, not a video recording.
A terminal recorder is not used for this small text-only fixture. The probe uses
real base source and candidate code with a synthetic transport; it makes no
network request, reads no credentials and changes no native files. It requires
the exact base Git object. These results do not prove installed Quipu or native
harness acceptance. Quipu versions retaining the old private file-memory guard
refuse ordinary writes to the retained revision IDs. Wait for the normal
reviewed primitive-removal installation; do not rename IDs or relax that guard.
