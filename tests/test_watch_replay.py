"""The offline template must refuse broken bindings and never perform effects."""
import json
from pathlib import Path
import pytest
from shantytown.watch_program import WatchRefused
from shantytown.watch_replay import _json, load_spec, main, replay

EXAMPLES = Path(__file__).resolve().parents[1] / 'docs/examples/watch'


def evidence(name='inactive'):
    return json.loads((EXAMPLES / (name + '.json')).read_text())


def test_two_source_formats_share_one_validator():
    assert load_spec(EXAMPLES/'watch.json') == load_spec(EXAMPLES/'watch.toml')


def test_inactive_safety_pass_cannot_credit_activation_or_compensation():
    result = replay(load_spec(EXAMPLES/'watch.toml'), evidence())
    assert result['result'] == dict(safety='PASS', activation='INACTIVE', improvement='NOT_EVALUATED', reasons=(), compensation='NOT_EXECUTED')
    assert result['actions_executed'] == result['jobs_launched'] == []
    assert result['next_sample_at'] is None


def test_breach_is_nonzero_and_does_not_launch_or_compensate(capsys):
    assert main(['--spec',str(EXAMPLES/'watch.toml'),'--evidence',str(EXAMPLES/'breach.json')]) == 1
    result=json.loads(capsys.readouterr().out)
    assert result['result']['safety'] == 'BREACH'
    assert result['actions_executed'] == result['jobs_launched'] == []


@pytest.mark.parametrize('key', ['run_id','source_digest','deployment_receipt'])
def test_foreign_binding_refused(key):
    value=evidence();value[key]='foreign'
    with pytest.raises(WatchRefused): replay(load_spec(EXAMPLES/'watch.toml'), value)


def test_resume_stays_on_original_grid_and_gap_has_no_cursor():
    spec=load_spec(EXAMPLES/'watch.toml');value=evidence();value['samples']=value['samples'][:2];value['now']=1045
    assert replay(spec,value)['next_sample_at'] == 1090
    value['samples'].pop(0)
    result=replay(spec,value)
    assert result['result']['safety'] == 'UNKNOWN'
    assert result['next_sample_at'] is None


@pytest.mark.parametrize('raw', ['{"version":1,"version":1}', '{"now":NaN}', '{"now":Infinity}'])
def test_ambiguous_json_refuses(raw):
    with pytest.raises(WatchRefused): _json(raw)


def test_oversize_and_nonregular_input_refuse(tmp_path):
    from shantytown.watch_replay import _read, MAX_BYTES
    path=tmp_path/'large';path.write_bytes(b' '* (MAX_BYTES+1))
    with pytest.raises(WatchRefused): _read(path)
    import os
    fifo=tmp_path/'pipe';os.mkfifo(fifo)
    with pytest.raises(WatchRefused): _read(fifo)


def test_unknown_command_fields_cannot_smuggle_actions():
    value=evidence();value['revert_command']='touch forbidden'
    with pytest.raises(WatchRefused): replay(load_spec(EXAMPLES/'watch.toml'),value)
