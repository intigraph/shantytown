"""Actual private publishers interleave; no production archive or mocked replace."""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/history_archive.py'
spec = importlib.util.spec_from_file_location('history_archive_lock_test', SCRIPT)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


@pytest.fixture
def citation(tmp_path):
    hot, cold = tmp_path/'hot/tester', tmp_path/'cold/tester'
    hot.mkdir(parents=True);cold.mkdir(parents=True, mode=0o700)
    target = cold/('a.jsonl.recaptured-' + hashlib.sha256(b'A').hexdigest()[:12])
    target.write_bytes(b'A');target.chmod(0o600)
    link = hot/'a.jsonl';link.symlink_to(target)
    return link, target


def test_interleaved_successful_predecessor_is_retained_or_competing_writer_refused(citation):
    link, target = citation
    before = os.readlink(link)
    published = []
    def outer(stream):
        try:
            archive.atomic_write(link, b'B')
        except ValueError as error:
            assert 'in progress' in str(error)
        else:
            published.append(b'B')
        stream.write(b'C')
    archive.publish(link, outer)
    retained = [p.read_bytes() for p in target.parent.glob('.history-preserved-*')]
    assert b'A' in retained
    assert all(value in retained for value in published), 'successful B publication lost'
    assert target.read_bytes() == b'C' and os.readlink(link) == before


def child_write(link, value):
    code = ('import sys;sys.path.insert(0,sys.argv[1]);'
            'from history_archive import atomic_write;'
            'atomic_write(sys.argv[2],sys.argv[3].encode())')
    return subprocess.run([sys.executable, '-B', '-c', code, str(SCRIPT.parent),
                           str(link), value], capture_output=True, text=True, timeout=5)


def test_other_process_cannot_publish_inside_transaction_and_successors_are_preserved(citation):
    link, target = citation
    def outer(stream):
        result = child_write(link, 'B')
        assert result.returncode != 0
        assert 'already in progress' in result.stderr
        assert target.read_bytes() == b'A'
        stream.write(b'C')
    archive.publish(link, outer)
    assert child_write(link, 'B').returncode == 0
    archive.atomic_write(link, b'D')
    retained = [p.read_bytes() for p in target.parent.glob('.history-preserved-*')]
    assert all(value in retained for value in (b'A', b'B', b'C'))
    assert target.read_bytes() == b'D'


def test_writer_failure_releases_lock_without_replacing_current_bytes(citation):
    link, target = citation
    def failed(stream):
        stream.write(b'incomplete')
        raise RuntimeError('synthetic interrupted writer')
    with pytest.raises(RuntimeError): archive.publish(link, failed)
    assert target.read_bytes() == b'A'
    assert child_write(link, 'B').returncode == 0
    assert target.read_bytes() == b'B'


@pytest.mark.parametrize('fault', ['public', 'symlink', 'hardlink'])
def test_unsafe_existing_lock_refuses_before_writer(citation, tmp_path, fault):
    link, target = citation
    key = hashlib.sha256(target.name.encode()).hexdigest()
    lock = target.parent/('.history-publish-' + key + '.lock')
    other = tmp_path/'other';other.write_bytes(b'keep');other.chmod(0o600)
    if fault == 'symlink': lock.symlink_to(other)
    elif fault == 'hardlink': os.link(other, lock)
    else: lock.write_bytes(b'');lock.chmod(0o644)
    def forbidden(stream): raise AssertionError('writer invoked')
    with pytest.raises((ValueError, OSError)):
        archive.publish(link, forbidden)
    assert target.read_bytes() == b'A' and other.read_bytes() == b'keep'
