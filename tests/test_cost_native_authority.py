import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from shantytown import cost


def test_selected_native_transport_never_contacts_br():
    tracker=Mock();tracker._bd.return_value=subprocess.CompletedProcess([],0,'{"id":"demo-one"}','')
    with patch.object(cost.subprocess,'run') as legacy:
        result=cost.show({'_backend':'seeds','_tracker':tracker},'demo-one')
    assert result['id']=='demo-one'
    tracker._bd.assert_called_once_with('show','demo-one','--json')
    legacy.assert_not_called()


def test_missing_or_failed_native_authority_never_falls_back():
    with patch.object(cost.subprocess,'run') as legacy:
        with pytest.raises(RuntimeError):cost.show({'_backend':'seeds'},'demo-one')
        tracker=Mock();tracker._bd.side_effect=TimeoutError('native unavailable')
        with pytest.raises(TimeoutError):cost.show({'_backend':'seeds','_tracker':tracker},'demo-one')
    legacy.assert_not_called()


def test_cli_refuses_unselected_backend_before_any_effect(tmp_path):
    (tmp_path/'cost.json').write_text('{}')
    from shantytown import cli
    with patch.object(cli,'_backend',return_value='files'),patch.object(cost,'_run_locked') as run:
        assert cost.run(SimpleNamespace(root=tmp_path,backend=None))==2
        run.assert_not_called()


def test_cli_proves_native_store_and_preserves_provider(tmp_path):
    (tmp_path/'cost.json').write_text('{}')
    from shantytown import cli
    tracker=Mock()
    with patch.object(cli,'_backend',return_value='seeds'),patch.object(cli,'_tracker',return_value=tracker),patch.object(cost,'_run_locked',return_value=0) as run:
        assert cost.run(SimpleNamespace(root=tmp_path,backend=None))==0
    tracker.prove_store.assert_called_once_with()
    assert run.call_args.args[1]['_tracker'] is tracker


def test_explicit_wrong_override_refuses(tmp_path):
    (tmp_path/'cost.json').write_text('{}')
    from shantytown import cli
    with patch.object(cli,'_backend',return_value='seeds'),patch.object(cli,'_tracker') as lookup:
        assert cost.run(SimpleNamespace(root=tmp_path,backend='br'))==2
        lookup.assert_not_called()
