"""Rolling DVR buffer storage on disk.

Layout: <root>/<stream_id>/<fragment_filename>
Fragment naming is up to the recorder; BufferManager only sorts and prunes by mtime.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path


class BufferManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def stream_dir(self, stream_id: int) -> Path:
        d = self.root / str(stream_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_fragments(self, stream_id: int) -> list[Path]:
        d = self.root / str(stream_id)
        if not d.is_dir():
            return []
        return sorted([p for p in d.iterdir() if p.is_file()])

    def total_bytes(self, stream_id: int) -> int:
        return sum(p.stat().st_size for p in self.list_fragments(stream_id))

    def prune_older_than(self, stream_id: int, retention_days: int) -> int:
        d = self.root / str(stream_id)
        if not d.is_dir():
            return 0
        cutoff = time.time() - retention_days * 86400
        bytes_freed = 0
        for p in self.list_fragments(stream_id):
            if p.stat().st_mtime < cutoff:
                bytes_freed += p.stat().st_size
                p.unlink()
        return bytes_freed

    def list_all_fragments(self) -> list[Path]:
        """Return every fragment file across all stream subdirs, sorted oldest-mtime first."""
        if not self.root.is_dir():
            return []
        files: list[Path] = []
        for stream_dir in self.root.iterdir():
            if stream_dir.is_dir():
                files.extend(p for p in stream_dir.iterdir() if p.is_file())
        files.sort(key=lambda p: p.stat().st_mtime)
        return files

    def prune_oldest_until_free(self, target_free_bytes: int) -> int:
        """Delete oldest fragments across all streams until at least `target_free_bytes`
        of free space is available on the buffer's filesystem, or there's nothing left
        to prune. Returns total bytes freed.
        """
        bytes_freed = 0
        try:
            free = shutil.disk_usage(self.root).free
        except OSError:
            return 0
        if free >= target_free_bytes:
            return 0
        for p in self.list_all_fragments():
            if free >= target_free_bytes:
                break
            try:
                size = p.stat().st_size
                p.unlink()
                bytes_freed += size
                free += size
            except OSError:
                continue
        return bytes_freed

    def free_space_ratio(self) -> float:
        """Fraction of the buffer filesystem that's free (0.0–1.0). Returns 1.0 on error."""
        try:
            usage = shutil.disk_usage(self.root)
        except OSError:
            return 1.0
        if usage.total == 0:
            return 1.0
        return usage.free / usage.total
