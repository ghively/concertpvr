import datetime as dt
from pathlib import Path

from PIL import Image

from concertpvr.metadata import MetadataBuilder, SegmentMeta


def _meta(**overrides) -> SegmentMeta:
    base = dict(
        artist="Phoebe Bridgers",
        title="Mojave Set",
        festival="Coachella W1",
        venue="Mojave Stage",
        year=2026,
        date=dt.date(2026, 4, 12),
        duration_s=4500,
        width=1920,
        height=1080,
    )
    base.update(overrides)
    return SegmentMeta(**base)


def test_build_nfo_writes_emby_movie_xml(tmp_path: Path):
    mb = MetadataBuilder()
    nfo = mb.build_nfo(_meta(), tmp_path)
    assert nfo == tmp_path / "movie.nfo"
    text = nfo.read_text(encoding="utf-8")
    assert text.startswith("<?xml")
    assert "<movie>" in text
    assert "<title>Phoebe Bridgers — Mojave Set</title>" in text
    assert "<year>2026</year>" in text
    assert "<premiered>2026-04-12</premiered>" in text
    assert "<runtime>75</runtime>" in text
    assert "<studio>Coachella W1</studio>" in text


def test_build_nfo_when_no_optional_metadata(tmp_path: Path):
    mb = MetadataBuilder()
    minimal = SegmentMeta(
        artist="Test",
        title=None,
        festival=None,
        venue=None,
        year=2026,
        date=None,
        duration_s=600,
        width=None,
        height=None,
    )
    nfo = mb.build_nfo(minimal, tmp_path)
    text = nfo.read_text(encoding="utf-8")
    assert "<title>Test</title>" in text
    assert "<premiered>" not in text


def test_build_poster_with_source_thumbnail(tmp_path: Path):
    src = tmp_path / "src.jpg"
    Image.new("RGB", (1280, 720), color=(20, 30, 50)).save(src, "JPEG")

    mb = MetadataBuilder()
    poster = mb.build_poster(_meta(), source_thumbnail=src, output_dir=tmp_path)
    assert poster == tmp_path / "poster.jpg"
    assert poster.exists() and poster.stat().st_size > 0

    img = Image.open(poster)
    assert abs((img.width / img.height) - (2 / 3)) < 0.01


def test_build_poster_without_source_falls_back_to_solid(tmp_path: Path):
    mb = MetadataBuilder()
    poster = mb.build_poster(_meta(), source_thumbnail=None, output_dir=tmp_path)
    assert poster.exists()
    img = Image.open(poster)
    assert abs((img.width / img.height) - (2 / 3)) < 0.01


def test_build_fanart_copies_or_renders(tmp_path: Path):
    src = tmp_path / "src.jpg"
    Image.new("RGB", (1280, 720), color=(20, 30, 50)).save(src, "JPEG")
    mb = MetadataBuilder()
    fan = mb.build_fanart(src, tmp_path)
    assert fan == tmp_path / "fanart.jpg"
    assert fan.exists()


def test_build_fanart_without_source_creates_default(tmp_path: Path):
    mb = MetadataBuilder()
    fan = mb.build_fanart(None, tmp_path)
    assert fan.exists()


def test_nfo_emits_multiple_genres(tmp_path: Path):
    mb = MetadataBuilder()
    nfo = mb.build_nfo(_meta(genres=["Indie", "Psych", "Funk"]), tmp_path)
    text = nfo.read_text(encoding="utf-8")
    assert "<genre>Indie</genre>" in text
    assert "<genre>Psych</genre>" in text
    assert "<genre>Funk</genre>" in text
    assert "<genre>Concert</genre>" not in text


def test_nfo_falls_back_to_concert_when_no_genres(tmp_path: Path):
    mb = MetadataBuilder()
    nfo = mb.build_nfo(_meta(), tmp_path)
    text = nfo.read_text(encoding="utf-8")
    assert "<genre>Concert</genre>" in text
    assert "<tag>concertpvr</tag>" in text


def test_nfo_skips_empty_genre_strings(tmp_path: Path):
    mb = MetadataBuilder()
    nfo = mb.build_nfo(_meta(genres=["Indie", "", "  "]), tmp_path)
    text = nfo.read_text(encoding="utf-8")
    assert "<genre>Indie</genre>" in text
    # Don't emit empty genre tags
    assert text.count("<genre>") == 1


def test_nfo_emits_plot_when_set(tmp_path: Path):
    mb = MetadataBuilder()
    nfo = mb.build_nfo(_meta(plot="A beautiful set from the rural Texas garage."), tmp_path)
    text = nfo.read_text(encoding="utf-8")
    assert "<plot>A beautiful set from the rural Texas garage.</plot>" in text


def test_nfo_omits_plot_when_none(tmp_path: Path):
    mb = MetadataBuilder()
    nfo = mb.build_nfo(_meta(), tmp_path)
    text = nfo.read_text(encoding="utf-8")
    assert "<plot>" not in text


def test_nfo_truncates_long_plot(tmp_path: Path):
    mb = MetadataBuilder()
    long_plot = "x" * 5000
    nfo = mb.build_nfo(_meta(plot=long_plot), tmp_path)
    text = nfo.read_text(encoding="utf-8")
    # Find the plot element and assert internal text length capped at 2000.
    start = text.find("<plot>") + len("<plot>")
    end = text.find("</plot>")
    assert end - start == 2000
