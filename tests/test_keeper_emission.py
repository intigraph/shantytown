"""Keeper deployment must pass the real shared settings emitter."""
import pytest

from shantytown import runtime
from shantytown.cli import _emit_role_settings


def declare(root, coordination='["absorbs", "dispatches"]'):
    (root / "shantytown.toml").write_text(
        '[roles.keeper]\nattachment="reports-to"\n'
        'workIntake=["dispatched", "self-directed"]\n'
        f'coordination={coordination}\n'
        'scope="domain-scoped"\nlifecycle="persistent"\n'
        'authority="veto-in-scope"\n')


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_keeper_real_emitter_preserves_send_haul_drain(tmp_path, harness):
    declare(tmp_path)
    assert runtime.role_stop_hooks("keeper", root=tmp_path) == runtime.role_stop_hooks(
        "lead", root=tmp_path)
    emitted = _emit_role_settings(tmp_path, {"keeper"}, harness_name=harness)
    assert len(emitted) == 1 and emitted[0].is_file()
    data = emitted[0].read_text()
    assert "send" in data and "haul" in data and "drain" in data


@pytest.mark.parametrize("coordination", [None, '["dispatches"]'])
def test_keeper_missing_or_nonabsorbing_declaration_refuses(tmp_path, coordination):
    if coordination is not None:
        declare(tmp_path, coordination)
    with pytest.raises(ValueError, match="deployment-declared absorbing"):
        runtime.role_stop_hooks("keeper", root=tmp_path)


def test_unknown_role_still_refuses(tmp_path):
    declare(tmp_path)
    with pytest.raises(ValueError, match="unknown role"):
        runtime.role_stop_hooks("unreviewed-role", root=tmp_path)
