"""Per-job-type ephemeral bounds (aegis-za4f D5).

The deployment shortened EVERY job to 10 minutes / 2 turns for reviews; a task
job inherited it and could not read, edit, test and open a PR. A job type with
its own [ephemeral.limits.<job>] entry gets its bounds; others keep the global.
"""
import pytest

from shantytown import config as config_mod
from shantytown import ephemeral as eph


def _load(tmp_path, body):
    (tmp_path / "shantytown.toml").write_text(body)
    return config_mod.load(tmp_path).ephemeral


def test_task_limits_override_only_the_task_job(tmp_path):
    policy = _load(tmp_path, "[ephemeral]\nlifetime_minutes = 10\nmax_turns = 2\n"
                             "[ephemeral.limits.task]\nlifetime_minutes = 90\nmax_turns = 60\n")
    assert policy.limits == {"task": {"lifetime_minutes": 90, "max_turns": 60}}
    common = dict(root=tmp_path, policy=policy, actor=None, administrator="sattler",
                  host="host-a", now=1000.0, role_of=lambda _: "administrator")
    task = eph.plan(eph.Request(job="task", item="aegis-za4f", repo="scbrown/shantytown"), **common)
    review = eph.plan(eph.Request(job="review", item="aegis-za4f", repo="scbrown/shantytown",
                                  pr=1), **common)
    assert (task["deadline"], task["max_turns"]) == (1000.0 + 90 * 60, 60)
    assert (review["deadline"], review["max_turns"]) == (1000.0 + 10 * 60, 2)


@pytest.mark.parametrize("body", [
    "[ephemeral.limits.nope]\nmax_turns = 3\n",
    "[ephemeral.limits.task]\nbudget = 3\n",
    "[ephemeral.limits.task]\nmax_turns = 0\n",
    "[ephemeral.limits.task]\nmax_turns = true\n",
    "[ephemeral]\nlimits = 3\n",
])
def test_bad_limits_refuse_at_load(tmp_path, body):
    if not body.startswith("[ephemeral]"):
        body = "[ephemeral]\n" + body
    with pytest.raises(config_mod.ConfigError):
        _load(tmp_path, body)
