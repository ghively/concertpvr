"""Generate Emby-compatible movie metadata files (NFO, poster, fanart)."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class SegmentMeta:
    artist: str
    title: str | None
    festival: str | None
    venue: str | None
    year: int
    date: _dt.date | None
    duration_s: int
    width: int | None
    height: int | None


POSTER_W: int = 1000
POSTER_H: int = 1500
FANART_W: int = 1920
FANART_H: int = 1080


class MetadataBuilder:
    def build_nfo(self, meta: SegmentMeta, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "movie.nfo"

        title = f"{meta.artist} — {meta.title}" if meta.title else meta.artist
        runtime = max(0, meta.duration_s // 60)

        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
            "<movie>",
            f"  <title>{escape(title)}</title>",
            f"  <originaltitle>{escape(title)}</originaltitle>",
            f"  <year>{meta.year}</year>",
            f"  <runtime>{runtime}</runtime>",
        ]
        if meta.date:
            lines.append(f"  <premiered>{meta.date.isoformat()}</premiered>")
        if meta.festival:
            lines.append(f"  <studio>{escape(meta.festival)}</studio>")
        if meta.venue:
            lines.append(f"  <set><name>{escape(meta.venue)}</name></set>")
        lines.append("  <genre>Concert</genre>")
        lines.append("  <tag>concertpvr</tag>")
        lines.append("</movie>")

        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    def build_poster(
        self, meta: SegmentMeta, source_thumbnail: Path | None, output_dir: Path
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "poster.jpg"

        canvas = Image.new("RGB", (POSTER_W, POSTER_H), color=(12, 14, 18))

        if source_thumbnail and source_thumbnail.exists():
            try:
                src = Image.open(source_thumbnail).convert("RGB")
                scale = max(POSTER_W / src.width, POSTER_H / src.height)
                new_size = (int(src.width * scale), int(src.height * scale))
                src = src.resize(new_size, Image.Resampling.LANCZOS)
                left = (src.width - POSTER_W) // 2
                top = (src.height - POSTER_H) // 2
                src = src.crop((left, top, left + POSTER_W, top + POSTER_H))
                overlay = Image.new("RGB", (POSTER_W, POSTER_H), color=(0, 0, 0))
                src = Image.blend(src, overlay, 0.4)
                canvas = src
            except Exception:
                pass

        draw = ImageDraw.Draw(canvas)
        artist_font, title_font, sub_font = self._load_fonts()

        artist_y = POSTER_H * 2 // 3
        draw.text((60, artist_y), meta.artist, fill=(232, 234, 238), font=artist_font)
        if meta.title:
            draw.text((60, artist_y + 90), meta.title, fill=(212, 102, 74), font=title_font)
        sub_lines: list[str] = []
        if meta.festival:
            sub_lines.append(meta.festival)
        if meta.venue and meta.venue != meta.festival:
            sub_lines.append(meta.venue)
        sub_lines.append(str(meta.year))
        sub_text = " · ".join(sub_lines)
        draw.text((60, artist_y + 180), sub_text, fill=(154, 160, 171), font=sub_font)

        canvas.save(out, "JPEG", quality=88)
        return out

    def build_fanart(self, source_thumbnail: Path | None, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "fanart.jpg"

        if source_thumbnail and source_thumbnail.exists():
            try:
                src = Image.open(source_thumbnail).convert("RGB")
                scale = max(FANART_W / src.width, FANART_H / src.height)
                new_size = (int(src.width * scale), int(src.height * scale))
                src = src.resize(new_size, Image.Resampling.LANCZOS)
                left = (src.width - FANART_W) // 2
                top = (src.height - FANART_H) // 2
                src = src.crop((left, top, left + FANART_W, top + FANART_H))
                src.save(out, "JPEG", quality=88)
                return out
            except Exception:
                pass

        Image.new("RGB", (FANART_W, FANART_H), color=(12, 14, 18)).save(out, "JPEG", quality=88)
        return out

    def _load_fonts(
        self,
    ) -> tuple[ImageFont.ImageFont, ImageFont.ImageFont, ImageFont.ImageFont]:
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ):
            if Path(candidate).exists():
                return (
                    ImageFont.truetype(candidate, 72),
                    ImageFont.truetype(candidate, 56),
                    ImageFont.truetype(candidate, 36),
                )  # type: ignore[return-value]
        d = ImageFont.load_default()
        return (d, d, d)  # type: ignore[return-value]
