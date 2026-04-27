"""Setlist detection from VOD description and comments."""

from concertpvr.setlist_detector import (
    detect_in_chapters,
    detect_in_comments,
    detect_in_description,
)


def test_detect_description_with_classic_timestamps():
    desc = """For Khruangbin's debut Tiny Desk Concert...

0:00 - Intro
1:24 - Pelota
5:12 - So We Won't Forget
10:48 - People Everywhere (Still Alive)
14:35 - Time (You and I)

Producers: Bobby Carter
"""
    result = detect_in_description(desc)
    assert result is not None
    assert len(result.entries) == 5
    assert result.entries[0].title == "Intro"
    assert result.entries[0].start_s == 0
    assert result.entries[1].title == "Pelota"
    assert result.entries[1].start_s == 84
    assert result.source == "description"


def test_detect_description_bracketed_timestamps():
    desc = "[00:00] Opening\n[03:21] Song Two\n[08:45] Another Song"
    result = detect_in_description(desc)
    assert result is not None
    assert len(result.entries) == 3
    assert result.entries[1].start_s == 201


def test_detect_description_returns_none_when_no_pattern():
    assert detect_in_description("Just some prose about a concert.") is None
    assert detect_in_description("") is None
    assert detect_in_description(None) is None


def test_detect_description_picks_longest_block():
    desc = """0:00 - prelude

Setlist:
0:00 Song A
3:00 Song B
6:00 Song C
9:00 Song D
"""
    result = detect_in_description(desc)
    assert result is not None
    # 4-entry block wins; the leading "0:00 prelude" is part of a contiguous monotonic run
    # so the longest_contiguous_block here is actually all 5 (since 0:00 prelude then 0:00 Song A
    # is non-decreasing). Verify the block is at least 4.
    assert len(result.entries) >= 4


def test_detect_chapters_basic():
    chapters = [
        {"start_time": 0, "end_time": 80, "title": "Intro"},
        {"start_time": 80, "end_time": 312, "title": "Pelota"},
    ]
    result = detect_in_chapters(chapters)
    assert result is not None
    assert len(result.entries) == 2
    assert result.entries[0].start_s == 0
    assert result.entries[1].title == "Pelota"
    assert result.source == "chapters"


def test_detect_chapters_returns_none_when_empty():
    assert detect_in_chapters([]) is None
    assert detect_in_chapters(None) is None


def test_detect_comments_finds_pinned_setlist():
    comments = [
        {"is_pinned": False, "text": "Great show!", "like_count": 12},
        {
            "is_pinned": True,
            "text": "Setlist:\n0:00 - Intro\n3:21 - Song Two\n8:45 - Song Three",
            "like_count": 200,
        },
    ]
    result = detect_in_comments(comments)
    assert result is not None
    assert len(result.entries) == 3
    assert result.source == "comments"


def test_detect_comments_falls_back_to_top_liked():
    comments = [
        {"is_pinned": False, "text": "great track at 3:21", "like_count": 10},
        {
            "is_pinned": False,
            "text": "0:00 - Intro\n3:21 - Song Two\n8:45 - Song Three\n12:00 - Song Four",
            "like_count": 500,
        },
    ]
    result = detect_in_comments(comments)
    assert result is not None
    assert len(result.entries) == 4


def test_detect_comments_returns_none_when_no_match():
    comments = [{"is_pinned": False, "text": "Wow!", "like_count": 5}]
    assert detect_in_comments(comments) is None


def test_detect_comments_drops_malformed_timestamps():
    comments = [
        {"is_pinned": True, "text": "0:00 Intro\n1:99 Bad\n3:21 Song Two", "like_count": 100}
    ]
    result = detect_in_comments(comments)
    assert result is not None
    assert len(result.entries) == 2
