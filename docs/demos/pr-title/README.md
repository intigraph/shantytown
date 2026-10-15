# Conventional squash title guard

Before: the required test jobs did not inspect PR titles. Nine of the 24
first-parent subjects in the 0.7.0 input range were unparseable. A tenth omission
was a valid `test:` subject hidden by the default changelog sections.

Run `python3 docs/demos/pr-title/reproduce.py` from the repository root. The
[recorded output](output.txt) comes from the actual CI event guard: the old
untyped title exits 1, while the corrected title and `test:` control exit 0.
The release configuration explicitly displays every supported type.

This local event replay does not prove repository settings, a hosted title-edit
check, or a resulting merge subject. Those are separate acceptance checks. Set
GitHub's squash commit title to **Pull request title** (`PR_TITLE`) after the
reviewed source gate is delivered. Existing release notes are not rewritten.
