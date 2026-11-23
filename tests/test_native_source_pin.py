"""Real local closure hashing, Git metadata and shared/exclusive custody leases."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shantytown import native_source_pin as pin, review_enqueue_native as adapter
from shantytown.actor_identity import IdentityError

REAL_VERIFIED=pin.verified
REAL_POLICY=pin.policy


@pytest.fixture
def source(tmp_path,monkeypatch):
    # Model protected fixture ancestry; /tmp itself is deliberately shared on
    # test hosts. Leaf custody, symlinks, hardlinks and bytes stay real.
    fstat=os.fstat
    outer={(p.stat().st_dev,p.stat().st_ino) for p in tmp_path.parents if p.stat().st_mode&0o022}
    def protected(fd):
        meta=fstat(fd)
        if (meta.st_dev,meta.st_ino) in outer:
            fields=list(meta);fields[0]&=~0o022;return os.stat_result(fields)
        return meta
    monkeypatch.setattr(pin.os,'fstat',protected)
    root=tmp_path/'source';root.mkdir(mode=0o700)
    (root/'scripts').mkdir(mode=0o700);(root/'scripts'/'pr-risk.py').write_text('print("fixture")\n');(root/'scripts'/'pr-risk.py').chmod(0o600)
    (root/'lib').mkdir(mode=0o700);(root/'lib'/'guard.py').write_text('ALLOW=False\n');(root/'lib'/'guard.py').chmod(0o600)
    (root/'README.md').write_text('fixture closure\n');(root/'README.md').chmod(0o600)
    def git(*args):
        env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_TERMINAL_PROMPT='0')
        return subprocess.run([pin.GIT,'-c','core.hooksPath=/dev/null','-c','init.templateDir=',
            '-c','user.name=fixture','-c','user.email=fixture@example.invalid',
            '-C',str(root),*args],capture_output=True,check=True,env=env,umask=0o077)
    git('init','-q');git('add','.');git('commit','-qm','fixture')
    proof=pin.measure(root,os.geteuid())
    lock=tmp_path/'source.lock';lock.write_text('')
    policy=tmp_path/'pin.json'
    value=dict(version=1,root=str(root),entrypoint='scripts/pr-risk.py',owner=os.geteuid(),
               revision=proof['revision'],closure_sha256=proof['closure_sha256'],lock_file=str(lock))
    def write(value=value):policy.write_text(json.dumps(value))
    write();monkeypatch.setattr(pin,'PIN',policy);monkeypatch.setattr(pin,'LOCK',lock)
    # Root-owned pin/lock installation is an explicit fixture seam, not a
    # production chown, sudo, enrollment or ownership relaxation.
    monkeypatch.setattr(adapter,'_operator_file',lambda p:os.open(p,os.O_RDONLY|os.O_NOFOLLOW))
    return root,root/'scripts'/'pr-risk.py',value,write,git


def test_current_exact_revision_and_complete_closure_qualify(source):
    root,native,value,_,_=source
    with pin.verified(native) as lease:
        assert lease.proof['revision']==value['revision']
        assert lease.proof['closure_sha256']==value['closure_sha256']
        assert lease.proof['file_count']==4  # Every tracked file plus local Git config.
        assert os.fstat(lease.fd).st_nlink==1


@pytest.mark.parametrize('fault',['bytes','same-mtime','untracked','missing','mode','owner','revision',
                                  'digest','git-config','external-config','symlink-escape','hardlink'])
def test_any_changed_closure_or_unknown_custody_refuses(source,fault):
    root,native,value,write,_=source
    leaf=root/'lib'/'guard.py'
    if fault in ('bytes','same-mtime'):
        before=leaf.stat();leaf.write_text('ALLOW=True \n')
        if fault=='same-mtime':os.utime(leaf,ns=(before.st_atime_ns,before.st_mtime_ns))
    elif fault=='untracked':(root/'lib'/'injected.py').write_text('bad')
    elif fault=='missing':leaf.unlink()
    elif fault=='mode':leaf.chmod(0o666)
    elif fault=='owner':value['owner']+=1;write()
    elif fault=='revision':value['revision']='d'*40;write()
    elif fault=='digest':value['closure_sha256']='d'*64;write()
    elif fault=='git-config':
        with (root/'.git'/'config').open('a') as stream:stream.write('\n[core]\n bare = false\n')
    elif fault=='external-config':
        with (root/'.git'/'config').open('a') as stream:stream.write('\n[include]\n path = /outside/config\n')
    elif fault=='symlink-escape':leaf.unlink();leaf.symlink_to('/outside/guard.py')
    elif fault=='hardlink':os.link(leaf,root.parent/'another-link')
    with pytest.raises((IdentityError,OSError,subprocess.SubprocessError)): 
        with pin.verified(native):pytest.fail('mismatch admitted')


def test_tracked_file_links_are_in_closure_and_bytecode_is_bypassed(source):
    root,native,value,write,git=source
    (root/'ALIAS.md').symlink_to('README.md');git('add','.');git('commit','-qm','alias')
    proof=pin.measure(root,os.geteuid());value.update({k:proof[k] for k in ('revision','closure_sha256')});write()
    cache=root/'lib'/'__pycache__';cache.mkdir();(cache/'guard.cpython-314.pyc').write_bytes(b'inert cache')
    with pin.verified(native):pass
    value['entrypoint']='lib/__pycache__/guard.cpython-314.pyc';write()
    with pytest.raises(IdentityError):
        with pin.verified(root/value['entrypoint']):pytest.fail('unverified cache entrypoint admitted')


def test_refresh_and_execution_serialize_on_one_fixed_lease(source):
    _,native,_,_,_=source
    with pin.verified(native):
        with pytest.raises(BlockingIOError):
            with pin.refreshing():pytest.fail('refresh interleaved with execution')
    with pin.refreshing():
        with pytest.raises(BlockingIOError):
            with pin.verified(native):pytest.fail('execution interleaved with refresh')
    with pin.verified(native):pass


def test_native_child_keeps_lease_when_adapter_parent_releases_it(source):
    _,native,_,_,_=source
    with pin.verified(native) as lease:
        process=subprocess.Popen([sys.executable,'-I','-S','-c',
            'import sys;print("ready",flush=True);sys.stdin.read(1)'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,pass_fds=(lease.fd,))
        assert process.stdout.readline().strip()=='ready'
    try:
        with pytest.raises(BlockingIOError):
            with pin.refreshing():pytest.fail('orphan native child lost source lease')
    finally:process.communicate('x',timeout=10)
    with pin.refreshing():pass


def test_source_pin_never_falls_back_to_another_path_or_absent_pin(source,monkeypatch):
    _,native,_,_,_=source
    with pytest.raises(IdentityError):
        with pin.verified(native.with_name('another.py')):pytest.fail('fallback path admitted')
    pin.PIN.unlink()
    with pytest.raises(FileNotFoundError):
        with pin.verified(native):pytest.fail('missing pin admitted')
    with pin.refreshing() as adopted:assert adopted is None


@pytest.mark.parametrize('fault',['owner','revision','digest','entrypoint','unknown','duplicate','lock'])
def test_malformed_or_unknown_operator_pin_refuses(source,fault):
    _,native,value,write,_=source
    if fault=='owner':value['owner']=True
    elif fault=='revision':value['revision']='main'
    elif fault=='digest':value['closure_sha256']='unknown'
    elif fault=='entrypoint':value['entrypoint']='../outside.py'
    elif fault=='unknown':value['unknown']=1
    elif fault=='lock':value['lock_file']='/another/lock'
    if fault=='duplicate':pin.PIN.write_text('{"version":1,"version":1}')
    else:write()
    with pytest.raises((IdentityError,KeyError,TypeError)):
        with pin.verified(native):pytest.fail('malformed pin admitted')


def test_metadata_normalization_requires_recomputed_operator_pin(source):
    root,native,value,write,_=source
    (root/'.git').chmod(0o775);(root/'.git'/'config').chmod(0o664)
    with pytest.raises(IdentityError):pin.measure(root,value['owner'])
    (root/'.git').chmod(0o755);(root/'.git'/'config').chmod(0o644)
    with pytest.raises(IdentityError):
        with pin.verified(native):pytest.fail('permission change reused old closure pin')
    proof=pin.measure(root,value['owner'])
    assert proof['closure_sha256']!=value['closure_sha256']
    value['closure_sha256']=proof['closure_sha256'];write()
    with pin.verified(native):pass


def test_refresh_fd_must_be_exact_operator_lock_and_pinned_root(source):
    root,_,_,_,_=source
    other=os.open(root/'README.md',os.O_RDONLY)
    try:
        with pytest.raises(IdentityError):pin.check_refresh_fd(other,root)
    finally:os.close(other)
    with pin.refreshing() as lease:
        assert pin.check_refresh_fd(lease.fd,root)['root']==str(root)
        with pytest.raises(IdentityError):pin.check_refresh_fd(lease.fd,root.parent)


@pytest.mark.parametrize('bound',['MAX_FILES','MAX_BYTES'])
def test_exhausted_closure_bound_is_unknown_not_a_partial_pin(source,monkeypatch,bound):
    root,_,value,_,_=source
    monkeypatch.setattr(pin,bound,1)
    with pytest.raises(IdentityError):pin.measure(root,value['owner'])


def test_native_flags_bypass_a_real_poisoned_bytecode_cache(source):
    import importlib.util
    import py_compile
    root,native,value,write,git=source
    native.write_text("import sys,pathlib;sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'lib'));import guard;print(guard.ALLOW)\n")
    git('add','.');git('commit','-qm','import fixture')
    leaf=root/'lib'/'guard.py';before=leaf.stat();original=leaf.read_bytes()
    leaf.write_bytes(b'ALLOW=True \n');os.utime(leaf,ns=(before.st_atime_ns,before.st_mtime_ns))
    cache=Path(importlib.util.cache_from_source(str(leaf)));cache.parent.mkdir(mode=0o700)
    py_compile.compile(str(leaf),cfile=str(cache),doraise=True)
    leaf.write_bytes(original);os.utime(leaf,ns=(before.st_atime_ns,before.st_mtime_ns))
    proof=pin.measure(root,value['owner']);value.update({k:proof[k] for k in ('revision','closure_sha256')});write()
    ordinary=subprocess.run([sys.executable,'-I','-S','-B',str(native)],capture_output=True,text=True,check=True)
    assert ordinary.stdout.strip()=='True'  # Positive control: the poison is usable.
    with pin.verified(native) as lease:
        actual=subprocess.run([sys.executable,'-I','-S','-B','-X','pycache_prefix=/dev/null',str(native)],
            capture_output=True,text=True,check=True,pass_fds=(lease.fd,))
    assert actual.stdout.strip()=='False'


def test_excluded_cache_directory_cannot_hide_source_or_redirects(source):
    root,native,_,_,_=source
    cache=root/'lib'/'__pycache__';cache.mkdir(mode=0o700)
    (cache/'__init__.py').write_text('untracked package code')
    with pytest.raises(IdentityError):
        with pin.verified(native):pytest.fail('untracked package escaped closure')


def test_busy_refresh_is_a_deferred_tick_without_running_callback(source,monkeypatch,capsys):
    _,native,_,_,_=source
    monkeypatch.setattr(sys,'argv',['native-source-pin','refresh','--','/operator/never-run'])
    with pin.verified(native):assert pin.main()==0
    assert 'SKIP source refresh: native source lease busy' in capsys.readouterr().out


def test_refresh_callback_inherits_verified_exclusive_descriptor(source,monkeypatch):
    root,_,_,_,_=source
    calls=[]
    def run(argv,**kw):
        fd=int(kw['env']['AEGIS_NATIVE_SOURCE_REFRESH_FD'])
        assert kw['pass_fds']==(fd,)
        assert pin.check_refresh_fd(fd,root)['root']==str(root)
        calls.append(argv)
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr(pin.subprocess,'run',run)
    monkeypatch.setattr(sys,'argv',['native-source-pin','refresh','--','/operator/refresh','--check'])
    assert pin.main()==0
    assert calls==[['/operator/refresh','--check']]


def test_source_pin_demo_current_mutated_and_refresh_controls(source):
    root,native,_,_,_=source
    with pin.verified(native) as lease:
        print('Current pinned source: VERIFIED; closure files:',lease.proof['file_count'])
        with pytest.raises(BlockingIOError):
            with pin.refreshing():pytest.fail('refresh passed active reader')
        print('Refresh during native use: DEFERRED by exclusive lease')
    leaf=root/'lib'/'guard.py';before=leaf.stat();leaf.write_text('ALLOW=True \n')
    os.utime(leaf,ns=(before.st_atime_ns,before.st_mtime_ns))
    with pytest.raises(IdentityError) as refused:
        with pin.verified(native):pytest.fail('changed source admitted')
    print('Same-size/same-mtime mutation:',str(refused.value))
