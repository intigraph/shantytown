"""Private source fixtures only: no index, crew process or release is changed."""
from pathlib import Path
import runpy
import os

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
namespace = runpy.run_path(str(ROOT / "scripts/test-repository-knowledge.py"))
case = namespace["Knowledge"]()
case.setUp()
try:
    case.test_disjoint_cli_edits_merge_both_orders_without_registry_cure()
    print("BEFORE: disjoint CLI edits update one committed digest -> registry conflict.")
    print("AFTER: A then B and B then A -> clean merge, identical source bytes.")
    print("AFTER: renderer emits merged-byte SHA256; registry/summary witness unchanged.")
    print("CONTROL: concurrent reviewed-summary edits still conflict.")
    case.test_summary_anchor_missing_changed_or_rebound_refuses()
    print("CONTROL: missing/tampered summary anchor refuses; explicit reviewed update works.")
    print("Source fixtures only; no installed or live pipeline acceptance claimed.")
finally:
    case.doCleanups()
