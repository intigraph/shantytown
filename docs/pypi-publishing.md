# PyPI publishing

Release tests, tag/version/source identity, wheel startup and checksums gate the
normal release job. A separate `pypi` job uploads the same checked wheel and
sdist with GitHub OIDC. Only that job receives `id-token: write`; it runs no
repository code and uses the `pypi` GitHub environment. No PyPI password or API
token is required.

## One owner-account setup

On [PyPI account publishing](https://pypi.org/manage/account/publishing/), the
account owner adds a **pending GitHub Trusted Publisher** with:

| Field | Value |
| --- | --- |
| PyPI project name | `shantytown` |
| GitHub owner | `scbrown` |
| GitHub repository | `shantytown` |
| Workflow filename | `release.yml` |
| GitHub environment | `pypi` |

A pending publisher creates the project on its first successful upload; it does
not reserve the name beforehand. If the project already exists, its owner adds
the same publisher under that project's Publishing settings instead.

See the official [pending publisher instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [OIDC publishing contract](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## First publication and recovery

After registration and the reviewed workflow merge, run **Release** on **main**
with `release_tag: v0.6.0` to backfill the existing GitHub release. This path
requires a published stable release, verifies the two exact distribution names,
checksums, package metadata and console entry point, and checks metadata and
installed startup before the isolated upload job. It creates no tag or GitHub
release and does not rebuild an old release from current main.

Future successful normal releases publish automatically after their existing
gates. A failed or cancelled gate cannot reach PyPI. PyPI uploads are immutable:
if an upload fails, inspect PyPI's project/version JSON and the action result
before retrying. Do not enable `skip-existing` to hide a partial upload or a
conflicting release. Source rollback prevents future publishing; it does not
remove an already published distribution. A defective published release needs
an owner decision to yank it and a corrected new version.
