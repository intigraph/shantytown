# Attended review reports and enqueue

With `ephemeral.review_enqueue_enabled = true`, an attended review captures
the open pull request's head at launch. Its approval report must name that
same head. The controller writes the existing signed verdict, then rechecks
the forge identity, current head and pinned signer before retaining an enqueue
intent. A missing or untrusted approval cannot call the adapter.

Attended and protected reports use the same durable custody protocol and configured
`ephemeral.review_enqueue_command`. The command is an absolute argv array,
not a shell command. The attended adapter can be selected as:

```toml
[ephemeral]
review_enqueue_enabled = false
review_enqueue_attended_uid = 1000
review_enqueue_attended_dir = "/srv/crew/attended-enqueue"
review_enqueue_command = ["/opt/crew/bin/python3", "-I", "-B", "-m", "shantytown.review_enqueue_attended", "--root", "/srv/shantytown", "--native", "/opt/aegis/scripts/pr-risk.py", "--python", "/usr/bin/python3"]
```

These paths are examples; select the controller's explicit Unix UID, installed
interpreter, controller configuration root and neutral native execution source.
The native Python must have the dependencies of the ordinary native command;
the `st` interpreter may contain a different dependency set.

Provision the state directory and its `intents` and `bindings` children as
controller-owned 0700 directories. Every ancestor must be controller/root-owned
and non-group-writable, with no symlinks. Use a new private path instead of
changing permissions on a shared checkout. The directory-FD custody backend is
currently Linux-only; unsupported platforms refuse before launching a review.

Enroll repositories in `bindings/repositories.json`, a private 0600 single-link
file. It has a closed mapping of repositories to absolute local checkouts:

```json
{"version":1,"repositories":{"example/project":{"checkout":"/srv/checkouts/project"}}}
```

The adapter freshly verifies the signed approval and forge head, durably claims
one classification attempt, then calls the ordinary native `classify` and
`enqueue --diff-bound --execute` path. Classification identity, complete green
checks, holds and queue admission remain enforced. No merge executor is added.

The protected-UID adapter keeps its separate controller and source policies.
This attended contract uses the configured controller UID and private state;
it does not adopt or change the protected policies.

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
