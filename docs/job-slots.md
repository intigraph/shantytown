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

Generate provision-only identities with `python -m shantytown.job_catalog`, using
`--first-uid`, `--count`, `--controller-uid`, `--kind` and a new `--output`.
Retain each existing manifest with paired `--retain` and `--retain-sha256`
arguments. Retained bytes are never reserialized. Duplicate retained principals,
UIDs or accounts, mixed controllers, job/controller UID overlap and changed pins
refuse before output. `--kind` applies to new identities; a retained slot keeps
its original kind. Regenerate from the actual post-migration retained manifest,
not an earlier catalog draft. The compatibility fixture reproduces the original
65-slot catalog pin while the new negative controls reject its known defects.

## Non-interactive reserved-account setup

Tambo's explicit `job-slots --apply --resume` delegates to the installed
Shantytown helper's fixed root-only `resume-accounts inventory CATALOG_SHA256`
operation. It accepts no arbitrary path, command or caller-selected account.
The per-controller sudo fragment does not grant this operation. Kernel root,
native macOS, immutable installed code, the exact protected catalog and native
account readbacks are prerequisites. The tool shares the account lock with the
existing provisioner and the consumed-UID lock with launch and migration.

Setup reserves all fresh identities before the first account change. It resumes
untouched prepared accounts and can reconcile a fully verified account after a
lost completion write. Completed accounts and completed migration receipts are
verified without being recreated or rewritten. Partial native identities,
unknown reads, changed reservations, incomplete migrations and consumed UIDs
never cause blind replay or account adoption. They remain refused for explicit
reviewed recovery. Existing Tambo account setup remains in place; migrating that
older implementation is separate work.

Native verification also inventories every user's primary GID and the full job-group
record. A foreign primary-group user, named or UUID member, nested group, or
unreadable membership refuses completion and retains the reservation. Explicit
UUID members require the job user's independently read GeneratedUID. Fresh
reservation admission requires a complete primary-GID census too.

New accounts have their own primary group, disabled authentication and login,
negative admin-membership proof, and a private home. This component performs no
key enrollment, verdict registration or job launch, and never opens the
unattended gate. Signing-key lifecycle remains per spawn, not a reusable key per
slot. The root-only setup path is non-interactive and belongs to installation;
there is no attended-first activation mode.
