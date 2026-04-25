"""Rolling DVR buffer storage on disk.

Layout: <root>/<stream_id>/<fragment_filename>
Fragment naming is up to the recorder; BufferManager only sorts and prunes by mtime.
"""

from __future__ import annotations

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
