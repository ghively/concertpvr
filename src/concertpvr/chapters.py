"""Extract chapter metadata from a yt-dlp output directory."""

from __future__ import annotations

import json
from pathlib import Path


def extract_chapters_json(directory: Path) -> str | None:
    """Search `directory` (recursively) for a .info.json file with chapters.

    Returns the chapters JSON serialized as a string (suitable for
    Recording.raw_chapters_json), or None if no chapters were found.
    """
    if not directory.is_dir():
        return None
    for info_file in directory.rglob("*.info.json"):
        try:
            data = json.loads(info_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        chapters = data.get("chapters")
        if chapters and isinstance(chapters, list):
            return json.dumps(chapters)
    return None
