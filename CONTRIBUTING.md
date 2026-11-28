# Contributing to shantytown

shantytown runs a crew of coding agents. It is a pure Python package with
**one runtime dependency** (`cryptography`), installed as an editable package
by the crews that use it.

That last detail shapes almost everything below. Because consumers install with
`pip install -e .`, `main` is what the next `git pull` becomes: a bad merge here
reaches every consumer at once rather than one service. Please run the checks
before you push.

## Prerequisites

- Python **3.11 or newer** (`requires-python = ">=3.11"`)
- the `test` extra: `pytest`, `rdflib` and `PyYAML`

Nothing else. There is no compiler step, no lockfile to honour, and no service
to stand up in order to run the suite.

## Setup

```bash
git clone <this repository>
cd shantytown
python3 -m pip install -e .
python3 -m pip install ".[test]"
```

`pip install -e .` installs the package **and** its console scripts, `st` and
`st-context`.

## The checks CI runs

CI runs on every push to `main` and on every pull request, across Python 3.11,
3.12, 3.13 and 3.14. Run these three locally first; they catch most failures:

```bash
python3 -m pytest -q                 # 1. the suite
st --version                        # 2. the console script actually runs
python3 -c "import shantytown, tomllib, pathlib; \
  v = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version']; \
  assert shantytown.__version__ == v, (shantytown.__version__, v)"
                                    # 3. the two version constants agree
```

CI also runs these, which you can run yourself when a change touches them:

| check | command |
|---|---|
| The pull request title follows the convention below | `python scripts/check-pr-title.py` |
| No private key is tracked | `python3 scripts/check-private-keys.py` |
| The suite passes with hostile operator settings in the environment | CI only, on Python 3.14 |
| The suite passes in any test order | `bash scripts/check-test-order-independence.sh` |
| The repository knowledge witnesses match their sources | `python3 scripts/test-repository-knowledge.py` |
| The book builds | `mdbook build`, when `docs/` or `book.toml` changes |

The matrix is deliberately `fail-fast: false`. "3.11 broke" and "every version
broke" are different diagnoses, and running every version is the only thing that
can tell them apart, so please do not read one red cell as a general failure.

### Why check 2 exists

A package that imports cleanly but whose entry point does not run is a broken
install that the entire suite still passes, because the tests import modules
directly rather than invoking the script. `st --version` is the cheapest thing
that would have caught it.

### Why check 3 exists

The version is a hand-maintained constant in **two** places — `pyproject.toml`
and `shantytown/__init__.py` — kept in sync by hand with no guard. A bump that
updates one and forgets the other ships a CLI whose `--version` disagrees with
its own package metadata. If you bump the version, bump both.

## Two standing constraints

**One runtime dependency, and no more without an argument.** The package
depends on `cryptography`, which the signed recruiter requests use to check
signatures. Everything else is the standard library, and that is what lets a
consumer install this into almost any environment without negotiating a
dependency graph. A change that adds another runtime import from outside the
standard library needs to argue for itself in the pull request. Test-only and
development dependencies are a different question and are fine.

**3.11 is a floor, not a formality.** It is a promise to anyone installing on an
older interpreter. Please do not reach for syntax or standard-library APIs newer
than 3.11 without saying so — the matrix will catch it, but it is cheaper to
know before CI does.

## Tests

The suite lives in `tests/` and runs with no network, no fixtures to provision
and no external services.

```bash
python3 -m pytest -q                       # everything
python3 -m pytest tests/test_worktree.py   # one file
python3 -m pytest -k worktree              # by name
```

New behaviour should come with a test that fails before the change and passes
after it. A test that passes both ways documents an intention rather than
verifying one.

## Pull requests

- Branch off `main` and keep the change focused on one thing.
- Explain **why** in the commit message, not just what. This codebase's comments
  carry their own reasoning — a reader six months out needs the argument more
  than the diff, which git already has.
- Make sure the three local checks above pass.
- If a change alters agent-facing behaviour, say so explicitly in the PR
  description: consumers pick it up on their next pull, without a release step.

## Reporting a problem

Please open an issue with:

- what you ran and what happened, including the exact command and its output;
- what you expected instead;
- your Python version and how you installed the package (`st --version` and
  `python3 --version` cover most of it).

A report that lets someone else reproduce the behaviour is worth several that
describe it.

## Documentation

`docs/` is the source of the [book](https://intigraph.github.io/shantytown/).
A page appears in the book only when `docs/SUMMARY.md` lists it, so add a new
page there and to `docs/map.md`. If you change behaviour a page describes,
change the page in the same pull request.

## Agent-facing documentation

`AGENTS.md` and `CLAUDE.md` in the repository root are instructions for coding
agents working **in** this repository, not documentation of the tool. If you are
a human contributor you can ignore them; if you are an agent, read them first —
they take precedence over this file where the two overlap.

## Licence

Apache-2.0 — see `LICENSE`. Contributions are accepted under the same licence.

## Pull request and squash titles

Use `type: summary` or `type(scope): summary`, with an optional `!` before
the colon for a breaking change. Supported types are `feat`, `fix`, `perf`,
`refactor`, `docs`, `test`, `chore`, `ci`, and `build`. For example,
`fix(inbox): retain unread messages on a failed close`.

The required CI test jobs validate the PR title, including after title edits.
The repository squash setting must be **Pull request title** (`PR_TITLE`) so
a single-commit PR also uses the validated title. Keep this setting when changing
repository merge options. All supported types have visible release-note sections;
`test:` and maintenance changes are included as well as features and fixes.
