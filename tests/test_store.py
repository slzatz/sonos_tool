import pytest

from sonos_tool import store
from sonos_tool.errors import NoSearchResults, SonosToolError

TRACK = {"title": "Heart of Gold", "artist": "Neil Young", "album": "Harvest", "item_id": "catalog/tracks/X/", "uri": "soco://x"}


def test_search_round_trip(sonos_home):
    store.save_search("track", [TRACK, {**TRACK, "title": "Old Man"}])
    assert store.load_search("track")[1]["title"] == "Old Man"
    assert (sonos_home / "search_results" / "track_search.json").is_file()


def test_load_search_missing_raises(sonos_home):
    with pytest.raises(NoSearchResults):
        store.load_search("album")


def test_pick_search_results_validates_range(sonos_home):
    store.save_search("track", [TRACK])
    assert store.pick_search_results("track", [1]) == [TRACK]
    with pytest.raises(SonosToolError, match="out of range"):
        store.pick_search_results("track", [2])


def test_playlists_are_extensionless_files(sonos_home):
    n = store.append_to_playlist("mix", TRACK)
    assert n == 1
    assert (sonos_home / "playlists" / "mix").is_file()
    assert store.list_playlists() == ["mix"]
    assert store.load_playlist("mix") == [TRACK]


def test_playlist_missing_raises(sonos_home):
    with pytest.raises(SonosToolError, match="not found"):
        store.load_playlist("nope")


def test_playlist_name_validation(sonos_home):
    with pytest.raises(SonosToolError):
        store.playlist_path("../evil")
