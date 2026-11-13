# Mixed provisioned and launch-ready job slots

A protected catalog can contain both provision-only identities and complete
frozen launch capabilities. Every entry must have its exact reviewed hash and
unique UID/account; controller UIDs cannot be job UIDs. Identity-only slots have
exactly `version`, `principal`, `controller_uid`, `uid`, `gid`, `username`, `home`
and `root`. They are validated but are never candidates for selection or direct
privileged helper operations. Partial launch fields and malformed identities
refuse the whole catalog rather than being silently skipped.

`python -m shantytown.job_manifest` generates a new reviewed catalog without
installing it. Supply `--directory`, its exact `--catalog-sha256`, a `--bindings`
JSON file and its `--bindings-sha256`, and a new `--output` directory. The bindings
object maps each selected identity principal to all eight frozen launch fields:
`controller_root`, `workspace`, `settings`, `harness`, `request`, `argv`,
`environment`, and `review`. Each slot has its own exact request and command.

The renderer shares the launcher's value validator. It cannot edit identities,
replace existing complete capabilities, infer live controller state or overwrite
an output directory. Unchanged manifest bytes are preserved, and the resulting
catalog pins every new manifest digest. All input validation finishes before
output starts; retain incomplete output after an I/O error for inspection.

The generated directory is an artifact, not a privileged installation. Installing
it, re-pinning the exact helper policy, native UID/key checks and enabling jobs
remain separate operator steps. Existing consumed UIDs and uncertain launch
receipts are never reset or recycled. Use Tambo's reviewed account-resume and
exact policy-replacement paths for provisioned inventories; neither command
launches a job or substitutes controller credentials.
