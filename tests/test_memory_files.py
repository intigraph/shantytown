"""Lossless transport and external-editor controls; no live memory or network."""
import os
import pytest

from shantytown import memory_files as mf


def test_generation_keeps_full_index_topics_and_exact_bytes(tmp_path):
    original = tmp_path / "native"
    original.mkdir()
    (original / "topics").mkdir()
    index = b"\xef\xbb\xbf# Notes\r\n[topic](topics/one.md)\r\n" + b"line\r\n" * 210
    (original / "MEMORY.md").write_bytes(index)
    (original / "topics/one.md").write_text("Unicode: λ\n")
    files = mf.snapshot(original)
    staged = mf.stage(files, tmp_path)
    assert staged != original and mf.snapshot(staged) == files
    assert (staged / "MEMORY.md").read_bytes() == index
    assert (original / "MEMORY.md").read_bytes() == index
    assert (staged.stat().st_mode & 0o777) == 0o700


def test_external_edit_after_snapshot_survives_staging(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    path = native / "MEMORY.md"
    path.write_text("base")
    files = mf.snapshot(native)
    # Simulates an editor after final hash validation, before export begins.
    path.write_text("UNSYNCED EXTERNAL EDIT")
    generation = mf.stage(files, tmp_path)
    assert path.read_text() == "UNSYNCED EXTERNAL EDIT"
    assert (generation / "MEMORY.md").read_text() == "base"


def test_interrupted_export_never_rolls_back_over_external_edit(tmp_path, monkeypatch):
    native = tmp_path / "MEMORY.md"
    native.write_text("old")
    files = (mf.MemoryFile("MEMORY.md", b"new"),)
    def interrupted(fd):
        native.write_text("later external edit")
        raise OSError("synthetic interruption")
    monkeypatch.setattr(mf.os, "fsync", interrupted)
    with pytest.raises(OSError):
        mf.stage(files, tmp_path)
    assert native.read_text() == "later external edit"
    assert list(tmp_path.glob("memory-generation-*"))  # retained, never selected


@pytest.mark.parametrize("path", ["../x", "/x", "a/../x", "a//x", "a\\x", "", "./x"])
def test_unsafe_paths_refuse(path):
    with pytest.raises(mf.UnsafeMemory):
        mf.MemoryFile(path, b"synthetic")


@pytest.mark.parametrize("kind", ["symlink", "directory-link", "hardlink", "fifo"])
def test_unsafe_entries_refuse(tmp_path, kind):
    native = tmp_path / "native"
    native.mkdir()
    other = tmp_path / "other"
    other.write_text("other owner")
    path = native / "MEMORY.md"
    if kind == "symlink":
        path.symlink_to(other)
    elif kind == "directory-link":
        path.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "hardlink":
        os.link(other, path)
    else:
        os.mkfifo(path)
    with pytest.raises(mf.UnsafeMemory):
        mf.snapshot(native)
    assert other.read_text() == "other owner"


def test_invalid_utf8_and_oversize_refuse():
    for data in (b"\xff", b"x" * (mf.MAX_FILE_BYTES + 1)):
        with pytest.raises(mf.UnsafeMemory):
            mf.MemoryFile("MEMORY.md", data)


def test_duplicate_and_parent_collision_refuse(tmp_path):
    f = mf.MemoryFile("topic", b"one")
    for files in ((f, f), (f, mf.MemoryFile("topic/child", b"two"))):
        with pytest.raises(mf.UnsafeMemory):
            mf.stage(files, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_file_count_bound_and_root_symlink_refuse(tmp_path):
    files = tuple(mf.MemoryFile(f"{n}.md", b"x") for n in range(mf.MAX_FILES + 1))
    with pytest.raises(mf.UnsafeMemory):
        mf.stage(files, tmp_path)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(mf.UnsafeMemory):
        mf.snapshot(link)


def test_unsupported_filesystem_refuses_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "SECURE_FDS", False)
    with pytest.raises(mf.UnsafeMemory):
        mf.snapshot(tmp_path)
    with pytest.raises(mf.UnsafeMemory):
        mf.stage((mf.MemoryFile("note", b"x"),), tmp_path)
    assert not list(tmp_path.iterdir())


def test_mutable_or_nonbyte_content_refuses():
    for data in (bytearray(b"x"), "x"):
        with pytest.raises(mf.UnsafeMemory):
            mf.MemoryFile("note", data)
