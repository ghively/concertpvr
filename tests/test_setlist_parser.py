from pathlib import Path

import pytest

from concertpvr.setlist_parser import ParseError, parse_setlist_paste


def test_parses_unicode_em_dash():
    result = parse_setlist_paste("Phoebe Bridgers · 00:21–01:34")
    assert len(result) == 1
    assert result[0].artist == "Phoebe Bridgers"
    assert result[0].start_s == 21
    assert result[0].end_s == 60 + 34


def test_parses_ascii_dash():
    result = parse_setlist_paste("Goose · 1:51 - 3:42")
    assert result[0].start_s == 1 * 60 + 51
    assert result[0].end_s == 3 * 60 + 42


def test_parses_to_separator():
    result = parse_setlist_paste("Tame Impala · 05:31 to 07:05")
    assert result[0].start_s == 5 * 60 + 31


def test_parses_multiline():
    fixture = Path(__file__).parent / "fixtures" / "setlist_paste.txt"
    result = parse_setlist_paste(fixture.read_text(encoding="utf-8"))
    assert len(result) == 4
    assert {e.artist for e in result} == {"Phoebe Bridgers", "Goose", "Rüfüs Du Sol", "Tame Impala"}


def test_skips_empty_lines_and_comments():
    text = """
# Coachella W1
Phoebe Bridgers · 00:21–01:34

Goose · 1:51 - 3:42
"""
    result = parse_setlist_paste(text)
    assert len(result) == 2


def test_raises_on_unparseable_line():
    with pytest.raises(ParseError):
        parse_setlist_paste("totally invalid garbage")
