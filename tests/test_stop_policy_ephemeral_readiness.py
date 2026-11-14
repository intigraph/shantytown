"""A nominal slot cannot block a stop when launch admission forbids it."""
import json

import pytest

from shantytown import ephemeral, stop_policy


def host(tmp_path, *, unattended=None, ready=False, dangerous=True):
    settings = f"[ephemeral]\nmax_agents = 2\nunattended_uid_ready = {str(ready).lower()}\n"
    if unattended is not None:
        settings += f"unattended = {str(unattended).lower()}\n"
    (tmp_path / "shantytown.toml").write_text(settings)
    crew = tmp_path / "crew"
    crew.mkdir()
    (crew / "boss.json").write_text(json.dumps({
        "role": "administrator", "dangerous": dangerous,
    }))
    return tmp_path


@pytest.mark.parametrize("unattended", [None, True])
def test_unready_unattended_slots_cannot_block_admin_stop(tmp_path, unattended):
    root = host(tmp_path, unattended=unattended)
    slots = stop_policy.ephemeral_free_slots(root)
    verdict = stop_policy.decide(stop_policy.Inputs(
        me="boss", role="administrator",
        p0_plate=[stop_policy.P0Item("work", owner="")],
        capacity=stop_policy.Capacity(ephemeral_slots=slots),
    ))
    assert slots == 0
    assert not verdict.block


@pytest.mark.parametrize("unattended,dangerous,ready", [
    (True, True, True), (None, True, True),
    (False, True, False), (None, False, False),
])
def test_launchable_posture_counts_only_unoccupied_slots(
        tmp_path, unattended, dangerous, ready):
    root = host(tmp_path, unattended=unattended, dangerous=dangerous, ready=ready)
    ephemeral.write(root, {"name": "eph-task-000001", "state": ephemeral.LIVE})
    assert stop_policy.ephemeral_free_slots(root) == 1


def test_no_administrator_cannot_offer_spawn_capacity(tmp_path):
    assert stop_policy.ephemeral_free_slots(tmp_path) == 0
