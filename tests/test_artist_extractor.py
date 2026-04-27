from concertpvr.artist_extractor import extract_artist


def test_tiny_desk_pattern_colon():
    regex = r"^(?P<artist>.+?)\s*[:|]\s*(?:NPR Music )?Tiny Desk Concert"
    assert extract_artist("Khruangbin: Tiny Desk Concert", regex) == "Khruangbin"


def test_tiny_desk_pattern_pipe():
    regex = r"^(?P<artist>.+?)\s*[:|]\s*(?:NPR Music )?Tiny Desk Concert"
    assert extract_artist("Olivia Rodrigo | Tiny Desk Concert (Home)", regex) == "Olivia Rodrigo"


def test_kexp_pattern():
    regex = r"^(?P<artist>.+?)\s*-\s*Live on KEXP"
    assert extract_artist("Big Thief - Live on KEXP", regex) == "Big Thief"


def test_returns_none_when_no_match():
    regex = r"^(?P<artist>.+?):\s*Tiny Desk Concert"
    assert extract_artist("Just some other video", regex) is None


def test_returns_none_when_artist_group_empty():
    regex = r"^(?P<artist>.*?):\s*Tiny Desk Concert"
    assert extract_artist(": Tiny Desk Concert", regex) is None


def test_returns_none_when_regex_is_none_or_empty():
    assert extract_artist("Anything", None) is None
    assert extract_artist("Anything", "") is None


def test_unicode_preserved():
    regex = r"^(?P<artist>.+?)\s*[:|]"
    assert extract_artist("Sigur Rós: Tiny Desk", regex) == "Sigur Rós"


def test_strips_whitespace():
    regex = r"^(?P<artist>.+?):"
    assert extract_artist("  Khruangbin  : Tiny Desk", regex) == "Khruangbin"
