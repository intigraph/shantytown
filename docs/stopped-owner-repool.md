# Stopped-owner work in fleet tend

The existing fleet tend pass checks local registered owners. An explicit stop or
hold supplies its recorded start time; otherwise positively observed pane absence
starts a persisted interval. A sanctioned relaunch generation resets that interval.
Unknown process observations do not establish absence.

An owner holding any eligible P0/P1 work has a 30 minute threshold. Other owners
have a four hour threshold. Eligible open/in-progress work returns to
open/unassigned with a comment naming its holder. ASK/desk decisions, inbox
pointers, deploy reservations, and items with blocker/deferral metadata are excluded.
The lifecycle lock, a fresh ownership observation and the tracker revision fence
protect the transition. The tracker verifies both the comment and final fields.
An uncertain transition is journaled before submission and is never blindly retried.

`st fleet tend --dry-run` prints proposed transitions without recording detector
observations or issuing tracker writes. Existing stopped-recipient inbox warnings
remain visible; an inbox pointer is never delivered work or a repool candidate.

This slice supplies the detector only. Its tests and demo use isolated fixtures;
do not run a production census/backfill as part of source qualification. Duty
registries, stop-time prevention, metrics and administrator backfill are separate.
