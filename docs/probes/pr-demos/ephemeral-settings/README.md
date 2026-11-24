# Retire completed-job configuration

Run `python3 docs/probes/pr-demos/ephemeral-settings/reproduce.py` from the repository.
It uses a temporary store and the actual reaper, without launching agents or
accessing live settings. Replay the recording with
`scriptreplay --timing timing.log --log-out output.log` from this directory.

Before, a completed job leaves one unknown-role configuration in the hook check.
The dry run proposes retirement. The real reap archives the emitted config with
`.retired`, leaving zero unknown-role files and preserving both configuration
bytes and job history. Live and unknown jobs remain checked. This fixture does
not demonstrate deployment or the recurring alarm's 14-day quiet acceptance.
