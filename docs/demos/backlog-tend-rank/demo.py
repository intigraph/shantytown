"""Replay actual base/head ranking sweeps with an isolated graph-order fixture."""
import hashlib
import importlib.util
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from shantytown import backlog_rank_report, ranking_check
from shantytown.answer import Answer
from shantytown.sd import StoreProof

BASE = "d0e8899ae8bf8553637e9859baae6bb4bb918338"
ROOT = Path(__file__).resolve().parents[3]


def main():
    source = subprocess.run(["git", "show", BASE + ":shantytown/ranking_check.py"],
                            cwd=ROOT, capture_output=True, check=True).stdout
    proof = StoreProof("--quipu", None, "https://example.test", "test", "urn:test:board")
    ready = [dict(id=name, title="ordinary work", priority=1, status="open",
                  assignee=None, labels=[], created_at="2026-11-01T00:00:00Z")
             for name in ("old", "due")]
    ready[1]["due_at"] = "2026-11-07T00:00:00Z"
    original = repr(ready)
    reg = SimpleNamespace(all=lambda: Answer.complete_read([], how="isolated demo"))
    panes = SimpleNamespace(exists=lambda pane: True)
    def forbidden(*a, **kw):
        raise AssertionError("no external notification or tracker action is admitted")
    with tempfile.TemporaryDirectory() as scratch:
        base_file = Path(scratch) / "base_ranking.py"
        base_file.write_bytes(source)
        spec = importlib.util.spec_from_file_location("shantytown._demo_base_ranking", base_file)
        before = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = before
        spec.loader.exec_module(before)
        print("Isolated actual ranking sweeps; same READY input, fixture graph order.")
        print("BASE", BASE, "ranking source sha256", hashlib.sha256(source).hexdigest())
        print("HEAD ranking source sha256", hashlib.sha256(Path(ranking_check.__file__).read_bytes()).hexdigest())
        print("HEAD observer source sha256", hashlib.sha256(Path(backlog_rank_report.__file__).read_bytes()).hexdigest())
        for label, module in (("BEFORE", before), ("AFTER", ranking_check)):
            calls, logs = [], []
            def reader(root, name, params, **bounds):
                assert name == "seeds_work_rank_v2"
                calls.append(name)
                return [dict(row, revision=3, sampled_at=params["now"],
                             deferral_observation="UNKNOWN") for row in reversed(ready)]
            with patch.object(backlog_rank_report, "deployment_default", return_value="1"), \
                 patch.object(backlog_rank_report, "resolve_server", return_value=proof.quipu_url), \
                 patch.object(backlog_rank_report, "ask", side_effect=reader):
                kwargs = dict(snapshot=lambda: (ready, ready), log=logs.append,
                              counts_reader=lambda root: "fixture counts", push=forbidden)
                if "rank_store" in inspect.signature(module.sweep).parameters:
                    kwargs["rank_store"] = lambda: proof
                module.sweep(Path(scratch) / label, reg, panes, **kwargs)
            observations = [line for line in logs if line.startswith("graph rank observation:")]
            print(label, "named-query reads", len(calls), "graph observations", len(observations))
            for line in observations:
                print(line)
            assert len(calls) == (label == "AFTER")
            assert len(observations) == (label == "AFTER")
        assert repr(ready) == original
        print("CONTROL input unchanged; zero tracker actions and external notifications.")
        print("LIMIT fixture graph order; no live query, deployment, admission or global ranking proof.")


if __name__ == "__main__":
    main()
