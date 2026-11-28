# 🧭 Principles

- **Lean, not absent.** Orchestration is welcome — prioritization and event reactions — but it stays small: no convoys, no bus, no daemon zoo.
- **Bring your own tracker.** A directory of files, beads, `br`, Seeds or Forgejo issues. A tracker is three methods.
- **Ship no dashboard the harness feeds.** `st fleet dashboard` exists, but it is a read of the tracker
  and the cards; nothing on the dispatch path is written for its benefit.
- **Bring your own panes.** Bare tmux works. With [shanty](https://github.com/intigraph/shanty) on
  `PATH`, `st attach` opens the fleet's real panes under its themed bar without moving an agent off
  the fleet's socket. [herdr](https://github.com/ogulcancelik/herdr) or your own wrapper fit the
  same seam.
- **A check must be able to fail.** Anything that reports health must be shown returning red. The
  suite is large, and the tests that matter most are the ones proving a check *can* say no.
