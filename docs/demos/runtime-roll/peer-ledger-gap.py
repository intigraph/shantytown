"""Offline two-host admission fixture; no actual process or tracker writes."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument("--fail-write", type=int, choices=(1, 2), default=1)
args = parser.parse_args()
sys.path.insert(0, str(args.source))
from shantytown import runtime_roll as roll, runtime_update as update, cycle
from shantytown.protocols import Agent

with TemporaryDirectory() as temp, patch.object(update, "_manual_keep", return_value=False):
    roots = [Path(temp) / "host-a", Path(temp) / "host-b"]
    cards = [Agent(name="a"), Agent(name="b")]
    requests = [cycle.Requests(root) for root in roots]
    def sweep(index, evidence, block=""):
        return roll.sweep(roots[index], [cards[index]], requests=requests[index],
            observe=lambda *unused: evidence, boundary=lambda card: "",
            preflight=lambda card: None,
            checkpoint=lambda *unused: dict(text="synthetic durable snapshot"),
            fleet_block=block)
    sweep(0, update.Evidence("a-old", "2.1.319", "2.1.319"))
    real_write = roll.write_json_atomic
    calls = 0
    def fail(path, value):
        global calls
        calls += 1
        if calls == args.fail_write:
            raise OSError("synthetic ledger write failure")
        real_write(path, value)
    with patch.object(roll, "write_json_atomic", fail):
        try:
            sweep(0, update.Evidence("a-old", "2.1.319", "2.1.321"))
        except OSError:
            pass
    published = roll.ledger(roots[0])["a"]
    block = roll.peer_block([dict(host="host-a", error=None,
        agents=[dict(name="a", live=True, runtime_update=published)])])
    admitted = sweep(1, update.Evidence("b-old", "2.1.319", "2.1.321"), block)
    print(json.dumps(dict(failed_write=args.fail_write,
        host_a_pending=bool(requests[0].pending()),
        published_phase=published["phase"], peer_blocked=bool(block),
        host_b_admitted=admitted,
        pending_hosts=sum(bool(request.pending()) for request in requests)), sort_keys=True))
