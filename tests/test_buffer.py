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
