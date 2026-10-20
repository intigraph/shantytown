"""Record actual push-runner results with a modeled 121-second command.

No Git process or remote is contacted. PYTHONPATH selects the source revision.
The separate real 61-second hook measurement is documented in the caption.
"""
import json
import subprocess
from unittest.mock import patch

from shantytown import workspace


def modeled_hook(argv, timeout, **kwargs):
    if timeout < 121:
        raise subprocess.TimeoutExpired(argv, timeout)
    return subprocess.CompletedProcess(argv, 0, stdout="fixture peer accepted", stderr="")


with patch.object(workspace, "run_with_group_timeout", modeled_hook):
    for label, options in [("default", {}), ("explicit short control", {"timeout": 1})]:
        rc, stdout, stderr = workspace._git_push("fixture", "origin", "HEAD:topic", **options)
        print(json.dumps({"case": label, "rc": rc, "response": stdout or stderr}), flush=True)
