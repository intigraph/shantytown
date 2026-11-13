import json

import pytest

from shantytown.bobbin_scope import prepare


TEMPLATE = '''[[groups]]
name = "team"
repos = ["engine"]
[hooks]
search_group = "team"
[hooks.roles]
worker = ["team"]
'''


def source(root, role="worker", text=TEMPLATE):
    path = root / "provision" / "bobbin" / (role + ".toml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def apply(plan):
    for path, text in plan.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_projection_has_both_positive_and_unconfigured_fallback(tmp_path):
    root, ws = tmp_path / "root", tmp_path / "crew"
    assert prepare(root, ws, "worker") == {}
    source(root)
    first = prepare(root, ws, "worker")
    apply(first)
    assert prepare(root, ws, "worker") == first
    assert 'repos = ["engine"]' in (ws / ".bobbin/config.toml").read_text()
    assert json.loads((ws / ".bobbin/crew-scope-receipt.json").read_text())["role"] == "worker"
    with pytest.raises(ValueError, match="missing"):
        prepare(root, ws, "lead")


def test_existing_personal_config_and_projected_edits_are_preserved(tmp_path):
    root, ws = tmp_path / "root", tmp_path / "crew"
    source(root)
    target = ws / ".bobbin/config.toml"
    target.parent.mkdir(parents=True)
    target.write_text("# personal\n")
    with pytest.raises(ValueError, match="no projection receipt"):
        prepare(root, ws, "worker")
    assert target.read_text() == "# personal\n"
    target.unlink()
    apply(prepare(root, ws, "worker"))
    target.write_text(target.read_text() + "# personal edit\n")
    with pytest.raises(ValueError, match="changed after projection"):
        prepare(root, ws, "worker")
    assert target.read_text().endswith("# personal edit\n")


@pytest.mark.parametrize("text", [TEMPLATE.replace('search_group = "team"', 'search_group = "missing"'),
                                       '[server]\nurl = "https://example.test"\n'])
def test_bad_scope_never_becomes_an_unrestricted_projection(tmp_path, text):
    source(tmp_path, text=text)
    with pytest.raises(ValueError):
        prepare(tmp_path, tmp_path / "crew", "worker")
    assert not (tmp_path / "crew/.bobbin/config.toml").exists()
