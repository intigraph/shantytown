# Attended review reports and enqueue

With `ephemeral.review_enqueue_enabled = true`, an attended review captures
the open pull request's head at launch. Its approval report must name that
same head. The controller writes the existing signed verdict, then rechecks
the forge identity, current head and pinned signer before retaining an enqueue
intent. A missing or untrusted approval cannot call the adapter.

Attended and protected reports use the same durable custody and configured
`ephemeral.review_enqueue_command`. The command is an absolute argv array,
not a shell command. The existing automatic binding adapter can be selected as:

```toml
[ephemeral]
review_enqueue_enabled = false
review_enqueue_command = ["/usr/local/bin/python3", "-I", "-B", "-m", "shantytown.review_enqueue_bindings", "--root", "/srv/shantytown", "--bindings", "/srv/shantytown/review-bindings", "--native", "/opt/aegis/scripts/pr-risk.py"]
```

These paths are examples; use the installed interpreter, controller state and
admitted native execution source. Provision the private custody/binding
directories and repository enrollment separately. The native adapter still
requires its operator-owned controller and source policies, fresh native
classification, complete green checks and hold admission. This bridge does
not install those policies or waive their gates.

The flag defaults to false. Enabling it without a configured command refuses
configuration loading. Existing attended jobs launched without a bound head
cannot enqueue after a flag change; launch a fresh review in the proof window.

Every intent consumes an attempt before calling the adapter. Duplicate reports
reuse the retained outcome. A timeout or uncertain reply remains UNKNOWN and
does not authorize another enqueue, even if the same attended job signs a
later approval for that head. The first retained signature remains attached to
the consumed attempt. An adapter refusal or failure is included
in the job report, while normal reporting and detached teardown still run.
The normal merge queue performs landing; the review never starts a merge job.

Qualification must observe both refusal and positive enqueue on the real forge.
Offline signatures and a stub adapter demonstrate the report handoff, not a
live queue entry, a protected job UID or canonical runtime admission.
