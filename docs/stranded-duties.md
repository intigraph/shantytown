# Non-item duties in the stopped-owner sweep

The existing `stranded-owner-work` tend callback also reads a versioned local
duty inventory. It does not add a timer, launch a worker, edit an external
configuration, or infer that a quiet process is dead. Without an installed
inventory it reports UNKNOWN. Source installation alone does not activate the
inventory or prove fleet coverage.

The managed file is `<crew-root>/duties/registry.json`:

```json
{
  "schema": "shantytown.duties/1",
  "revision": 1,
  "coverage": ["merge-queue", "reviewer", "scheduled-job", "alert-keeper", "review-reservation", "haul"],
  "routing": {"internal-landing": {"repository_prefix": "internal/", "holder_rule": "author", "require_live": true}},
  "entries": [{
    "id": "example-queue",
    "kind": "merge-queue",
    "holder": "worker",
    "binding": "external",
    "priority": 0,
    "source": "example:reviewed-queue-configuration",
    "candidates": ["lead"],
    "authors": []
  }]
}
```

Coverage names declare the managed inventory's categories, not a claim that
every external producer has registered. Deployment acceptance must enumerate
the actual producers and bind their current source to these entries. In
particular, prose review reservations and shell commands are not parsed into
authority. Headless environment files, units, cron bindings, keeper sources and
haul owners need explicit reviewed inventory until their producers register
them. Do not count disabled templates or test expectations as serving rules.

Managed adoption supplies `internal-landing` as data: for the configured owner the PR author
owns landing and the main watch. A structured consumer calls
`Duties.send_landing()` at delivery time; the author must be positively live
under the lock shared with stop. No stopped-author send, queue fallback or
process wake is admitted. An older inventory without this rule cannot send.
The legacy global queue role is not an internal-repository landing policy.

On every admitted pass, literal agent bindings from enabled local job files
are refreshed using the existing job parser. Direct inbox/dispatch agents and
direct `env SHANTY_AGENT=...` argv assignments are supported. Role dispatch
already resolves a live role through its consumer. Shell programs, environment
files and units remain explicit external inventory. A malformed, changed,
oversized or symlinked job file makes duty coverage UNKNOWN; it cannot retire
the previous population. Successful removal of a job retires only that
producer's rows. A duty failure never blocks the independent item sweep.
The shared dry-run previews declared duties and newly discovered literal job
bindings without a lock, report, inventory refresh, message or remote intent.
Before enrollment it retains the existing item-only preview; the separate
duty summary remains UNKNOWN.

`binding: registry` is valid only when the actual consumer reads
`Duties.resolve()`. Eligible candidates must be positively live and not authors.
An atomic, revision-checked registry handoff changes that supported authority.
`binding: external` never changes by updating this registry: the sweep creates
one native idempotent P0 repair per duty and pages the live administrator.
Refiring uses the same workflow identity, including a lost create reply.
An acknowledged page does not mean the binding was repaired.

P0/P1 duties become due after 30 minutes; other priorities after four hours.
An independently recorded operator-stop time may establish that duration.
Other down/held evidence starts a measured interval. UNKNOWN or live evidence
resets duration proof. A pass admits at most ten effects; unserved duties are
visited before already filed/paged duties so a large census cannot starve.

With an inventory installed, `st agent stop NAME` lists work and duties before
stopping. It refuses until explicit `--repool-work` is supplied. Ordinary work
is revision-fenced with preservation metadata; ASK/desk decisions and deploy
reservations retain their exclusions. Supported duties hand off to eligible
live candidates; unsupported bindings get the repair item and page first.
The duty lock spans the actual stop. `--after-turn` cannot release held duties
while the agent still runs: finish the turn, then use the explicit stop path.
Internal self-cycles retain their identity and duty ownership.

Check a managed plan, then apply the exact observed inventory revision:

```sh
python -m shantytown.duties --root CREW_ROOT --plan PLAN.json --plan-sha256 REVIEWED_DIGEST --expected-revision 0
python -m shantytown.duties --root CREW_ROOT --plan PLAN.json --plan-sha256 REVIEWED_DIGEST --expected-revision 0 --apply
```

Plan omission does not retire a manual duty. Refresh preserves supported live
handoffs when the holder remains eligible. External holder changes require
actual consumer readback before the managed inventory changes.
The plan digest is checked against the actual bounded bytes read by each
command, so a changed path between rehearsal and apply cannot substitute data.

The existing pushgateway configuration publishes the `st_duties` group with
`shantytown_orphaned_duties{kind=...}`, census completeness and timestamp.
The same group also exports `shantytown_orphaned_work{kind="items"}` and
independent item-census completeness/timestamp. These read the existing
projection, attention and actual CAS outcomes, without another board query.
Item coverage is invalidated before a read: a failed projection cannot refresh
an old zero, while an independent duty handoff can still complete. Fresh
successful release readback counts zero; conflicts and unknown releases do not.
Partial or stale reads omit orphan counts; zero is emitted only for a fresh
complete declared census. A complete census is not evidence that an external
binding was fixed. Missing/stale metrics need a separate coverage alert.
The administrator's human anchor includes a bounded duty summary; JSON/short
anchor contracts stay unchanged. A separate live brief reader still requires
its managed adoption and reader-route acceptance.

Roll back through the reviewed source/configuration lane. Preserve inventory,
attention journals, repair items and receipts as evidence. Do not restore old
ownership blindly, delete repairs, or rerun an unknown remote intent with a
different identity. Installation acceptance remains open until the actual
scheduled pass, serving rule inventory, backfill, sustained zero and controlled
orphan alert have been observed.
