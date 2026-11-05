# Fresh owner guard read reduction

The same owner data returns the same item with **3 → 2 requests**. An empty
owner returns no items with **2 → 1 requests**. Removing the owned item's status
still refuses the read before any field hydration. Both versions use fresh
observations; no cross-invocation cache is introduced.

Run from the repository root with Python, pytest and RDFLib available:

```sh
PYTHONPATH=. python docs/probes/pr-demos/owner-guard-readcut/probe.py \
  --base ca672b4c8efff2f2e1471fe5728274cfdfd4fd89
```

The probe executes the actual SPARQL on private RDF data, without network calls.
Private native server controls also cover the copied served version. This
demonstrates command-level request reduction, not production request-rate or
latency recovery. Shared roster shape observations keep their existing path.
