"""EmbyClient path translation (v0.4.1)."""

from concertpvr.emby import EmbyClient


def test_pass_through_when_no_prefixes_set():
    c = EmbyClient("http://emby.local:8096", "key")
    assert c.translate_path("/data/publish/Khruangbin") == "/data/publish/Khruangbin"


def test_pass_through_when_only_local_prefix_set():
    c = EmbyClient("http://emby.local:8096", "key", local_prefix="/data/publish")
    assert c.translate_path("/data/publish/x") == "/data/publish/x"


def test_pass_through_when_only_emby_prefix_set():
    c = EmbyClient("http://emby.local:8096", "key", emby_prefix="/volume1/concerts")
    assert c.translate_path("/data/publish/x") == "/data/publish/x"


def test_translates_when_path_starts_with_local_prefix():
    c = EmbyClient(
        "http://emby.local:8096",
        "key",
        local_prefix="/data/publish",
        emby_prefix="/volume1/media/concerts",
    )
    assert (
        c.translate_path("/data/publish/Khruangbin - Tiny Desk")
        == "/volume1/media/concerts/Khruangbin - Tiny Desk"
    )


def test_unchanged_when_path_does_not_start_with_local_prefix():
    c = EmbyClient(
        "http://emby.local:8096",
        "key",
        local_prefix="/data/publish",
        emby_prefix="/volume1/media/concerts",
    )
    # Path outside the local prefix scope — leave alone.
    assert c.translate_path("/tmp/elsewhere") == "/tmp/elsewhere"


def test_windows_style_translation():
    c = EmbyClient(
        "http://emby.local:8096",
        "key",
        local_prefix="/data/publish",
        emby_prefix="Z:\\Media\\Concerts",
    )
    assert c.translate_path("/data/publish/Khruangbin") == "Z:\\Media\\Concerts/Khruangbin"


def test_empty_string_prefix_treated_as_unset():
    c = EmbyClient(
        "http://emby.local:8096",
        "key",
        local_prefix="",
        emby_prefix="/anything",
    )
    assert c.translate_path("/data/publish/x") == "/data/publish/x"
