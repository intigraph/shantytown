#!/usr/bin/env python3
"""Repeatable library demonstration; synthetic panes/versions, no live cycle."""
import argparse
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
sys.path.insert(0, str(args.source))

from shantytown import cycle, runtime_update as update  # noqa: E402
from shantytown.protocols import Agent  # noqa: E402

print("Fixture: two locally owned Claude sessions; running 2.1.319, installed 2.1.321")
print("No live panes, credentials, tracker writes or runtime processes are used.")
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    requests = cycle.Requests(root)
    if importlib.util.find_spec("shantytown.runtime_roll") is None:
        print("BASE: runtime update automatic roller is absent.")
        print("Pending replacement requests:", len(requests.pending()))
    else:
        from shantytown import runtime_roll as roll
        cards = [Agent(name=n, harness="claude") for n in ("first", "second")]
        versions = {c.name: update.Evidence(c.name + "-old", "2.1.319", "2.1.321") for c in cards}
        blockers = {"first": "the input box is not empty", "second": "background tasks running"}
        checkpoints = []
        def checkpoint(card, evidence):
            checkpoints.append(card.name)
            return dict(text="Stored anchor and resume notes for " + card.name, item="fixture-item", nodes=["existing-fixture-node"])
        def sweep():
            with patch.object(update, "_manual_keep", return_value=False):
                return roll.sweep(root, cards, requests=requests,
                    observe=lambda root, name: versions[name],
                    boundary=lambda card: blockers[card.name],
                    preflight=lambda card: None, checkpoint=checkpoint)
        print("CANDIDATE: typed input / background tasks ->", sweep())
        print("First blocker:", roll.ledger(root)["first"]["reason"])
        blockers.update(first="", second="")
        print("Both idle -> requested:", sweep())
        first = requests.pending()["first"]
        print("Checkpoint:", first["checkpoint"])
        print("Process replacement required:", first["no_in_place"])
        requests.clear("first")  # synthetic successful launch; version not yet observed
        print("Launch only -> next requested:", sweep())
        print("First phase:", roll.ledger(root)["first"]["phase"])
        versions["first"] = update.Evidence("first-new", "2.1.321", "2.1.321")
        print("Exact new-session version receipt -> next requested:", sweep())
        receipt = roll.ledger(root)["first"]["receipt"]
        print("Verified running version:", receipt["before"], "->", receipt["after"])
