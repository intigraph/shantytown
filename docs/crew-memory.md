# Crew memory across harnesses

The shared `CLAUDE.md` / `AGENTS.md` rulebook is separate from an agent's private
workspace memory. Codex does not discover Claude's project `memory/MEMORY.md`
through that rulebook link.

The existing SessionStart anchor bridges that memory into Codex context. It
resolves the runtime card's absolute workspace and effective harness, then reads
only the corresponding project index. For the legacy unnamed lane the source is
`~/.claude/projects/<encoded-workspace>/memory/MEMORY.md`. The workspace key uses
Claude's non-alphanumeric-to-hyphen spelling. A selected named account uses only
its existing account profile's `projects` directory; it never falls back to the
legacy profile or searches sibling accounts. Credential files are not read or
copied. Claude's own loading is unchanged.

This is a read-only bridge to the original file, not a second memory store or a
copy in `AGENTS.md`. It does not import sessions, enumerate unrelated projects,
or change the runtime card. The source path and loaded-text hash accompany the
notes. Historical notes require current verification and confer no new authority.

Startup output is bounded to 200 lines and 32 KiB of source text. A truncated
index explicitly warns that later directives may be omitted and points to the
original full index, which must be read before relying on the partial notes.
Unsafe, changing, invalid or unreadable memory reports UNKNOWN. A missing index
does not select another project's memory. The anchor still includes memory if a
tracker read fails; unknown tracker state remains unknown.

The existing emitted Codex SessionStart command exercises this path. Tests run
that command against isolated cards, memory and a file-backed fixture tracker;
they do not start or cycle a pane. A source test is not proof that an already
running session has loaded the change. Normal source review, CI and managed
arrival remain required before claiming installation.
