import pytest
from types import SimpleNamespace
from shantytown import cli

def test_cli_default_stays_live_and_display_decision_flags_refused(monkeypatch):
    args = SimpleNamespace(display_snapshot=True, governor=True)
    assert cli._cmd_crew(args) == 2
    parser = cli.build_parser()
    assert parser.parse_args(['crew']).display_snapshot is False
    with pytest.raises(SystemExit):
        parser.parse_args(['crew', '--display-snapshot', '--review-routing'])
