import json
from pathlib import Path

from concertpvr.chapters import extract_chapters_json


def test_returns_none_when_no_info_json(tmp_path: Path):
    assert extract_chapters_json(tmp_path) is None


def test_extracts_chapters_from_info_json(tmp_path: Path):
    info = tmp_path / "1234.info.json"
    info.write_text(json.dumps({
        "id": "abc",
        "chapters": [
            {"title": "Phoebe Bridgers", "start_time": 21, "end_time": 1900},
            {"title": "Goose", "start_time": 1900, "end_time": 4000},
        ],
    }))
    result = extract_chapters_json(tmp_path)
    assert result is not None
    parsed = json.loads(result)
    assert len(parsed) == 2
    assert parsed[0]["title"] == "Phoebe Bridgers"


def test_returns_none_when_info_has_no_chapters(tmp_path: Path):
    info = tmp_path / "1234.info.json"
    info.write_text(json.dumps({"id": "abc"}))
    assert extract_chapters_json(tmp_path) is None


def test_finds_info_json_in_subdirs(tmp_path: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "x.info.json").write_text(json.dumps({
        "chapters": [{"title": "X", "start_time": 0, "end_time": 10}],
    }))
    result = extract_chapters_json(tmp_path)
    assert result is not None
