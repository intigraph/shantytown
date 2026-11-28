# AGENTS.md

Instructions for coding agents working in this repository. `CLAUDE.md` is a symlink to
this file, so the two instruction surfaces cannot drift.

Repo-generic only: build, test and conventions. Deployment specifics belong wherever a
given deployment documents itself, not here.

## What this is

`shantytown` runs a crew of coding agents: work items, dispatch, roles, supervision and
budget controls. It installs two console scripts: `st` (`shantytown.cli:main`) and
`st-context` (`shantytown.work_context_command:main`), which reads one work item's context.

## Setup

```bash
python -m pip install -e .          # editable install; also installs the console scripts
python -m pip install ".[test]"     # pytest, rdflib and PyYAML, as CI installs them
```

**Runtime dependencies are allowed.** The project declares one today, `cryptography`,
which the signed recruiter requests use to check signatures. Add another when it does a
job the standard library does poorly. Consumers install this as an editable package, so
a new dependency reaches every install at once: name it and its reason in the change
rather than slipping it into the table.

Requires Python >= 3.11. CI runs the matrix 3.11, 3.12, 3.13, 3.14 — the declared floor
through the newest version, because testing only one end lets the other rot silently.

## Tests

```bash
python3 -m pytest -q            # testpaths = ["tests"]
```

Tests clear inherited `SHANTY_*`, `ST_*` and `QUIPU_SERVER` settings before each
case. Tests exercising these settings must set them explicitly through
`monkeypatch`. CI repeats the Python 3.14 suite with hostile operator defaults
set, so a clean runner cannot hide a leak into deployment configuration.

The suite collects more than 12,000 tests (measured 2026-11-27 with
`python3 -m pytest --collect-only -q`). Older counts are still quoted in places, such as
a CI comment that says 1770; treat any hard-coded count as a number that has already
drifted once, and re-measure rather than repeating it.

**A check must be able to fail.** This is the repo's own principle and it is the one most
worth honouring in new code: anything that reports health must be demonstrated returning
red. A test that cannot fail proves nothing. When you add a check, add the test that shows
it saying no.

## The version constant lives in TWO places

`pyproject.toml` (`project.version`) and `shantytown/__init__.py` (`__version__`). They
are kept in sync **by hand**, and CI asserts they agree. A bump that updates one and
forgets the other ships a CLI whose `--version` disagrees with its own package metadata.
Update both in the same commit.

## Packaging notes that have each broken something

- `[tool.setuptools] packages = ["shantytown"]` is declared explicitly because a
  top-level `assets/` directory gives flat-layout auto-discovery two candidate packages,
  and it refuses to guess.
- The `[build-system]` table is required for PEP 660 editable installs. Without it, an
  editable install fails in a way that silently freezes the installed version, so pulling
  the repo stops deploying anything.
- `setuptools>=77` is required by the PEP 639 `license = "Apache-2.0"` string form.

## Conventions

- Comments in this codebase explain **why**, usually by naming the failure that motivated
  the code. Match that: a comment that restates the line above it is noise, one that
  records what went wrong is why the file is readable a year later.
- Prefer small, direct functions over indirection. The stated principle is "lean, not
  absent" — orchestration is welcome, but no bus, no daemon zoo.
- Adapters are pluggable and the defaults are first-class; see `docs/adapters.md` before
  adding a hard-coded integration.

## Docs

`docs/` is the source of the book that CI builds with mdBook and publishes to GitHub
Pages. `docs/SUMMARY.md` is its table of contents: a page that is not listed there is not
in the book, so add a new page to `SUMMARY.md` and to `docs/map.md` in the same commit.
`cli.md` (commands), `configuration.md`, `roles.md`, `adapters.md` and `harnesses.md` are
the reference pages; `vision.md` and `design.md` are the original design record. If you
change behaviour a doc describes, change the doc in the same commit.

`tests/test_docs_drift.py` pins the README and several pages to the code: the command
list, the README's preview output, the environment variables in `configuration.md` and
the harness list. `docs/knowledge/repository-knowledge.json` holds a sha256 of `README.md`,
`CONTRIBUTING.md`, `docs/design.md`, `docs/configuration.md` and `docs/integrations.md`;
editing one of those files means updating its digest there, deliberately.
