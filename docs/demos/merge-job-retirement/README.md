# Merge job retirement

The same offline merge request is admitted on base
`f3e7f02015f5339bad8b8c87cbb38b8d9c8c372c` with review enqueue enabled,
then refused on this candidate. The flag-OFF control still admits it.
No job is launched and no forge is contacted. This is source behavior,
not deployment or approve-to-merge acceptance.

Run `PYTHONPATH=. python3 tests/demo_merge_job_retirement.py` from the repository.
The base source must be present in Git. The initial synthetic clock was below
the existing merge-spacing interval and was corrected to 1000 seconds; the
retirement guard and production behavior were unchanged by that demo repair.

[Output recording](output.txt) and [timing](timing.txt) are retained with this
source. Download both and replay with
`scriptreplay --log-out output.txt --log-timing timing.txt`.
The output also serves as the readable transcript; no inline video is claimed.
