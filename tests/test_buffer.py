import os
import time
from pathlib import Path

from concertpvr.buffer import BufferManager


def _touch(path: Path, content: bytes = b"x", mtime_offset_s: float = 0) -> None:
    path.write_bytes(content)
    if mtime_offset_s:
        new_mtime = time.time() - mtime_offset_s
        os.utime(path, (new_mtime, new_mtime))


def test_stream_dir_creates_on_first_call(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    d = mgr.stream_dir(42)
    assert d == tmp_path / "42"
    assert d.is_dir()


def test_list_fragments_returns_sorted(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    d = mgr.stream_dir(1)
    _touch(d / "20260425_120000.ts", b"a" * 100)
    _touch(d / "20260425_120010.ts", b"b" * 200)
    _touch(d / "20260425_115950.ts", b"c" * 50)
    fragments = mgr.list_fragments(1)
    assert [f.name for f in fragments] == [
        "20260425_115950.ts",
        "20260425_120000.ts",
        "20260425_120010.ts",
    ]


def test_total_bytes_sums_fragments(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    d = mgr.stream_dir(1)
    _touch(d / "a.ts", b"x" * 1024)
    _touch(d / "b.ts", b"y" * 2048)
    assert mgr.total_bytes(1) == 3072


def test_prune_older_than_removes_old_fragments(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    d = mgr.stream_dir(1)
    _touch(d / "old1.ts", b"o" * 100, mtime_offset_s=10 * 86400)
    _touch(d / "old2.ts", b"o" * 200, mtime_offset_s=8 * 86400)
    _touch(d / "fresh.ts", b"f" * 50, mtime_offset_s=1 * 86400)

    bytes_freed = mgr.prune_older_than(1, retention_days=7)
    assert bytes_freed == 300
    assert {f.name for f in mgr.list_fragments(1)} == {"fresh.ts"}


def test_prune_returns_zero_for_empty_stream(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    mgr.stream_dir(1)
    assert mgr.prune_older_than(1, retention_days=7) == 0


def test_prune_skips_unknown_stream(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    assert mgr.prune_older_than(999, retention_days=7) == 0


def test_list_all_fragments_returns_oldest_first(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    d1 = mgr.stream_dir(1)
    d2 = mgr.stream_dir(2)
    _touch(d1 / "a.ts", b"a", mtime_offset_s=10)  # newer
    _touch(d1 / "b.ts", b"b", mtime_offset_s=100)  # oldest
    _touch(d2 / "c.ts", b"c", mtime_offset_s=50)
    files = mgr.list_all_fragments()
    assert [p.name for p in files] == ["b.ts", "c.ts", "a.ts"]


def test_free_space_ratio_returns_value_between_zero_and_one(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    ratio = mgr.free_space_ratio()
    assert 0.0 <= ratio <= 1.0


def test_prune_oldest_until_free_no_op_when_already_above_target(tmp_path: Path):
    mgr = BufferManager(tmp_path)
    d = mgr.stream_dir(1)
    (d / "x.ts").write_bytes(b"x" * 100)
    # target=0 means "any amount of free space is fine" — never prunes.
    freed = mgr.prune_oldest_until_free(target_free_bytes=0)
    assert freed == 0
    assert (d / "x.ts").exists()


class _FakeUsage:
    def __init__(self, free: int) -> None:
        self.total = 10_000
        self.used = 10_000 - free
        self.free = free


def test_prune_oldest_until_free_deletes_oldest_first(tmp_path: Path, monkeypatch):
    """Patch disk_usage to return a controllable free counter that grows as files are deleted."""
    mgr = BufferManager(tmp_path)
    d1 = mgr.stream_dir(1)
    d2 = mgr.stream_dir(2)
    _touch(d1 / "old.ts", b"o" * 1000, mtime_offset_s=300)
    _touch(d2 / "mid.ts", b"m" * 1000, mtime_offset_s=200)
    _touch(d1 / "new.ts", b"n" * 1000, mtime_offset_s=100)

    # Compute "free" dynamically from what's still on disk; start = 500, each
    # delete adds the file's bytes back.
    initial_total_bytes = 3000

    def _fake_du(_p):
        existing = sum(p.stat().st_size for p in mgr.list_all_fragments())
        free_now = 500 + (initial_total_bytes - existing)
        return _FakeUsage(free=free_now)

    import concertpvr.buffer as buf_mod

    monkeypatch.setattr(buf_mod.shutil, "disk_usage", _fake_du)

    # Need free >= 2000. Start free = 500. Deleting the 1000-byte oldest file → free = 1500.
    # Deleting the 1000-byte middle file → free = 2500. Stop.
    freed = mgr.prune_oldest_until_free(target_free_bytes=2000)
    assert freed == 2000
    assert not (d1 / "old.ts").exists()  # oldest gone
    assert not (d2 / "mid.ts").exists()  # second-oldest gone
    assert (d1 / "new.ts").exists()  # newest preserved
