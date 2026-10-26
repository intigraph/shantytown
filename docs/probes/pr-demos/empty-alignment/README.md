# Exact empty alignment carrier demonstration

The same reviewed 401-byte carrier is refused by the base packager and accepted
by the candidate packager plus independent archive readback. A modified carrier
still refuses. This is a disposable synthetic library fixture, with no native
engine execution or trusted publisher invocation.

Base: `4c3d91b9941153c079c461f08590917c542b22e2`.
Candidate implementation: `3ad7c456372b65f6f45e3d61b2bc09cddc1219ea`.
The later demonstration-only commit preserves all four implementation/test blobs.

The output-only [recording](output.log.gz) and [timing](timing.log) were recorded
together using util-linux `script`; download both to replay. Inline playback is
not claimed. This small sanitized recording is retained in Git with the probe.

```sh
gzip -dc output.log.gz > output.log
scriptreplay --log-out output.log --log-timing timing.log
python3 docs/probes/pr-demos/empty-alignment/reproduce.py
```

The reproducer requires the base commit in the local Git object store. It calls
the actual source packaging/readback helpers; the manifest and engine provenance
are synthetic. Actual native artifact/provider acceptance, release publication
and installed behavior remain separate evidence requirements.
