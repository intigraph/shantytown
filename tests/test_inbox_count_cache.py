"""aegis-dnw: the status-bar `st inbox --count` poll is served from a short cache."""
import argparse
import json

from shantytown import cli, inbox_count_cache as cache
from shantytown.files import FilesTracker, items
from shantytown.inbox import TrackerInbox


def enable(monkeypatch, tmp_path, ttl='180'):
    monkeypatch.setenv('ST_INBOX_COUNT_TTL', ttl)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))


def counting_box(tmp_path, monkeypatch, count=3):
    tracker = FilesTracker(tmp_path / 'items')
    box = TrackerInbox(tracker, lambda: items(tracker))
    for i in range(count):
        box.deliver('reader', f'payload {i}')
    reads = []
    original = box.unread_count
    def unread_count(me):
        reads.append(me)
        return original(me)
    monkeypatch.setattr(box, 'unread_count', unread_count)
    monkeypatch.setattr(cli, '_inbox', lambda *a, **kw: box)
    return box, reads


def count_args():
    return argparse.Namespace(count=True, read=False, read_id=[], dry_run=False)


def test_second_count_is_served_without_a_store_read(tmp_path, monkeypatch, capsys):
    enable(monkeypatch, tmp_path)
    _, reads = counting_box(tmp_path, monkeypatch)
    assert cli._inbox_read(count_args(), 'reader') == cli.OK
    assert cli._inbox_read(count_args(), 'reader') == cli.OK
    assert capsys.readouterr().out.split() == ['3', '3']
    assert reads == ['reader']


def test_disabled_ttl_always_reads_the_store(tmp_path, monkeypatch, capsys):
    enable(monkeypatch, tmp_path, ttl='0')
    _, reads = counting_box(tmp_path, monkeypatch)
    cli._inbox_read(count_args(), 'reader')
    cli._inbox_read(count_args(), 'reader')
    assert reads == ['reader', 'reader']
    assert not (tmp_path / 'cache').exists()


def test_ack_and_new_mail_invalidate(tmp_path, monkeypatch, capsys):
    enable(monkeypatch, tmp_path)
    box, reads = counting_box(tmp_path, monkeypatch)
    cli._inbox_read(count_args(), 'reader')
    cache.invalidate('reader')            # what a durable send / ack does
    box.deliver('reader', 'late')
    cli._inbox_read(count_args(), 'reader')
    assert capsys.readouterr().out.split() == ['3', '4']
    assert reads == ['reader', 'reader']


def test_cmd_inbox_ack_drops_the_cached_count(tmp_path, monkeypatch, capsys):
    enable(monkeypatch, tmp_path)
    counting_box(tmp_path, monkeypatch)
    cache.put('reader', 99)
    a = argparse.Namespace(agent='reader', message=[], count=False, read=True, read_id=[],
                           dry_run=False, durable=False, routine=False, retain_pointer=False,
                           ack_id=None, defer_id=None, until=None, reason=None,
                           broadcast_to=[], delivery_key=None, json=False)
    assert cli._cmd_inbox(a) == cli.OK
    assert cache.get('reader') is None


def test_expired_foreign_future_and_corrupt_entries_are_misses(tmp_path, monkeypatch):
    enable(monkeypatch, tmp_path, ttl='60')
    cache.put('reader', 2, now=1000)
    assert cache.get('reader', now=1059) == 2
    assert cache.get('reader', now=1060) is None          # expired
    assert cache.get('reader', now=999) is None           # future-dated
    path = cache._path('reader')
    path.write_text(json.dumps({'agent': 'other', 'count': 1, 'at': 1000}))
    assert cache.get('reader', now=1001) is None          # foreign
    path.write_text('{not json')
    assert cache.get('reader', now=1001) is None          # corrupt
    path.write_text(json.dumps({'agent': 'reader', 'count': -1, 'at': 1000}))
    assert cache.get('reader', now=1001) is None          # impossible value


def test_unreadable_store_is_never_cached(tmp_path, monkeypatch, capsys):
    enable(monkeypatch, tmp_path)
    box, _ = counting_box(tmp_path, monkeypatch)
    def broken(me):
        raise RuntimeError('store down')
    monkeypatch.setattr(box, 'unread_count', broken)
    assert cli._inbox_read(count_args(), 'reader') == cli.CANNOT_TELL
    assert cache.get('reader') is None


def test_invalidate_accepts_an_agent_card_and_never_raises(tmp_path, monkeypatch):
    enable(monkeypatch, tmp_path)
    cache.put('reader', 5)
    class Card:
        name = 'reader'
    cache.invalidate(Card(), None, 42, '')
    assert cache.get('reader') is None
