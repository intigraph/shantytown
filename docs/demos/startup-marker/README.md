# Startup marker displaced after a confirmed first turn

The real startup-delivery function receives an exact-body Codex first-turn
receipt. The fake pane then shows subsequent work, with the startup marker
outside its terminal history. The base rejects this successful submission and
keeps mail unread; the candidate accepts it and acknowledges that one message.
Both send exactly once. Unsubmitted, queued and mismatched receipts still fail.

Run this script with a clean base checkout at
dbdce031b1f4f776251122eb69d265ecadc23bc2, then the candidate checkout:

    python3 docs/demos/startup-marker/reproduce.py /path/to/base
    python3 docs/demos/startup-marker/reproduce.py /path/to/candidate

This is a source demonstration with temporary file-backed mail and fake panes.
It launches no runtime and sends no live crew message.

[Recorded output](output.log) and [timing](timing.log) preserve both results.
Replay with scriptreplay --log-out docs/demos/startup-marker/output.log
--log-timing docs/demos/startup-marker/timing.log.
