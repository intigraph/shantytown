"""Pinned catalog render controls; writes private artifacts, never accounts."""
import hashlib
import json
from pathlib import Path

import pytest

from shantytown import job_catalog as catalog
from shantytown.actor_identity import IdentityError


@pytest.fixture
def retained(tmp_path):
    raw = (Path(__file__).parent/'fixtures/job-slots/eph-task-000001.json').read_bytes()
    path = tmp_path/'eph-task-000001.json'
    path.write_bytes(raw)
    assert hashlib.sha256(raw).hexdigest() == 'e985f7f8850b3c3cc6aaaba71865d426e9472a1737ac8c1a8be945e99e990890'
    return path, hashlib.sha256(raw).hexdigest()


def test_65_slot_render_reproduces_reviewed_pin_and_preserves_existing_slot(retained, tmp_path):
    path, digest = retained
    target = tmp_path/'catalog'
    result = catalog.render(60000,64,51000,'task',[retained],target)
    assert result == {'slots':65,'slots_json_sha256':'cc5aafc7ce063479e957013470de637f0c4e6c39109636eedb5152c35bb3235d'}
    assert (target/path.name).read_bytes() == path.read_bytes()
    assert len(json.loads((target/'slots.json').read_bytes())['slots']) == 65
    with pytest.raises(FileExistsError): catalog.render(60000,64,51000,'task',[retained],target)


@pytest.mark.parametrize('fault', ['repeated-retain','uid-overlap','mixed-controller','job-controller','partial-launch','changed-pin','wrong-filename'])
def test_retained_collisions_and_unreviewed_bytes_refuse_before_output(retained, tmp_path, fault):
    path, digest = retained
    row = json.loads(path.read_bytes())
    first = 60000
    if fault == 'uid-overlap': first = 51001
    elif fault == 'mixed-controller': row['controller_uid'] = 50000
    elif fault == 'job-controller': row.update(uid=51000,gid=51000)
    elif fault == 'partial-launch': row['harness'] = 'codex'
    if fault in ('mixed-controller','job-controller','partial-launch'):
        raw = json.dumps(row).encode();path.write_bytes(raw);digest=hashlib.sha256(raw).hexdigest()
    if fault == 'changed-pin': digest = '0'*64
    if fault == 'wrong-filename':
        new = path.with_name('foreign.json');path.rename(new);path=new
    retained = [(path,digest)] * (2 if fault == 'repeated-retain' else 1)
    target = tmp_path/'catalog'
    with pytest.raises(IdentityError): catalog.render(first,1,51000,'task',retained,target)
    assert not target.exists()


def test_kind_selects_new_slots_without_retyping_retained_slot(retained, tmp_path):
    target=tmp_path/'catalog'
    catalog.render(60000,1,51000,'review',[retained],target)
    assert (target/'eph-review-00ea60.json').is_file()
    assert (target/'eph-task-000001.json').read_bytes() == retained[0].read_bytes()


@pytest.mark.parametrize('first,count,controller', [(9999,1,51000),(60000,0,51000),(60000,1025,51000),(0xffffff,2,51000),(60000,1,60000)])
def test_invalid_or_unbounded_range_cannot_write(tmp_path, first, count, controller):
    target=tmp_path/'catalog'
    with pytest.raises(IdentityError): catalog.render(first,count,controller,'task',[],target)
    assert not target.exists()
