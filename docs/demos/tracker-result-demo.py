#!/usr/bin/env python3
"""Library boundary demo with a read-only failing tracker fixture."""
from argparse import Namespace
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from unittest.mock import patch
from urllib.error import HTTPError
from shantytown import cli

class Fixture:
    def get(self, item):
        raise HTTPError("https://example.invalid/query", 408, "fixture query timeout", None, None)

for structured in [False, True]:
    args = Namespace(cmd="item", item_action="show", item="fixture-1",
                     dry_run=False, result_json=structured)
    output, errors = StringIO(), StringIO()
    with patch.object(cli, "_tracker", return_value=Fixture()):
        with redirect_stdout(output), redirect_stderr(errors):
            code = cli._run_command(args)
    print("Structured mode" if structured else "Preserved legacy mode")
    print("operation: show fixture-1; simulated HTTP 408")
    print("exit:", code)
    assert code != 0
    if structured:
        value = json.loads(output.getvalue())
        assert value["ok"] is False and value["data"] is None
        assert value["error"]["category"] == "TIMEOUT"
        print(json.dumps(value, indent=2))
    else:
        print("stdout bytes:", len(output.getvalue()))
        print(errors.getvalue().strip())
print("The fixture performs no mutation, network request, retry or credential action.")
