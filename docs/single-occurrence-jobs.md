# One declared occurrence

The read-only `work jobs` catalogue accepts a Schedule with exactly one
`schema:repeatCount` integer 1. It still requires a valid whole-second,
offset-bearing `startDate`, timezone and fixed `repeatFrequency`; the count
limits that schedule to its first occurrence. Weekly/calendar qualifiers,
other counts, duplicate counts, wrong RDF types and end bounds refuse.
See [Schema.org repeatCount](https://schema.org/repeatCount).

JSON represents this form with `repeat_count: 1` and `interval_s: null`.
Fixed and weekly JSON shapes remain unchanged. Human output says `once at UTC
epoch ...`; it must never advertise a recurring interval for this declaration.

This is declaration support only. Executable admission, signed run status and
firing eligibility remain UNKNOWN. A consumer must understand the new form
explicitly; do not drop repeat_count or reinterpret null as an interval.
No write, schedule registration, identity migration or runtime execution is
performed by the reader.
