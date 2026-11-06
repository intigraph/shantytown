"""A tool launched by any harness must inherit that card's declared actor."""
import json
import os
import subprocess
import sys

import pytest

from shantytown.harness import get
from shantytown.protocols import Agent


@pytest.mark.parametrize("program", ["claude", "codex", "opencode"])
def test_tool_child_gets_card_actor_instead_of_inherited_actor(tmp_path, program):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    result = tmp_path / "identity.json"
    tool = bindir / "sd"
    tool.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib\n"
        f"pathlib.Path({str(result)!r}).write_text(json.dumps("
        "{key: os.environ.get(key) for key in "
        "('SHANTY_AGENT', 'BEADS_ACTOR', 'SEEDS_ACTOR')}))\n"
    )
    tool.chmod(0o700)
    harness = bindir / program
    harness.write_text(f"#!{sys.executable}\n"
                       "import subprocess\n"
                       "subprocess.run(['sd'], check=True)\n")
    harness.chmod(0o700)
    launch = get(program).launch(Agent("writer", harness=program),
                                 str(tmp_path / "settings.json"))
    subprocess.run(["/bin/sh", "-c", launch], check=True, env={
        "HOME": str(home), "PATH": str(bindir) + os.pathsep + os.defpath,
        "SHANTY_AGENT": "other-card", "BEADS_ACTOR": "other-card",
        "SEEDS_ACTOR": "other-card",
    })
    assert json.loads(result.read_text()) == {
        "SHANTY_AGENT": "writer", "BEADS_ACTOR": "writer",
        "SEEDS_ACTOR": "writer",
    }
