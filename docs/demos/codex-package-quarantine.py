"""Synthetic package migration demo; no daemon or live package is touched.

Run against the selected module: python3 docs/demos/codex-package-quarantine.py MODULE
Custody is stubbed only for the migration; a real held descriptor is a separate
negative control. Output omits temporary filesystem paths.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location("package_demo", sys.argv[1])
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    home, durable = root / "runtime", root / "disk" / "daemon"
    payload = home / "packages" / "app-server-daemon"
    payload.mkdir(parents=True)
    (payload / "release").write_bytes(b"retained payload")
    strict = packages.assert_quiescent
    packages.filesystem = lambda path: "ext4"
    packages.assert_quiescent = lambda path: None
    if hasattr(packages, "quarantine_custody"):
        packages.quarantine_custody = lambda path: {"coverage": "ESTABLISHED"}
    # The synthetic migration reports only the real counts below.
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        packages.migrate_stopped(home, durable)
    retained = [p for p in payload.parent.glob(".stopped-daemon-*") if p.is_dir()]
    print(f"shared payload bytes: {(durable / 'release').stat().st_size}")
    print(f"retained original trees: {len(retained)}")
    print(f"retained original bytes: {sum((p / 'release').stat().st_size for p in retained)}")
    control = root / "control"
    control.mkdir()
    (control / "held").write_bytes(b"held")
    with (control / "held").open("rb"):
        try:
            strict(control)
        except RuntimeError as error:
            assert "open descriptor" in str(error), str(error)
            print("real open-descriptor control: HOLD")
        else:
            raise AssertionError("live descriptor incorrectly admitted")
