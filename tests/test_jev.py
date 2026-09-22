"""jev.pick builds a Choice over the numbered results and maps the answer back."""

import pytest

from sonos_tool import jev
from sonos_tool.errors import ConfigError, SonosToolError

ITEMS = [
    {"title": "Traveling Alone", "artist": "Jason Isbell", "album": "Southeastern", "item_id": "a", "uri": "u"},
    {"title": "Traveling Alone (Live)", "artist": "Jason Isbell", "album": "Live from the Ryman", "item_id": "b", "uri": "v"},
]


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k-test")


def test_api_key_missing_is_config_error(sonos_home, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="TYPESAFE_API_KEY"):
        jev.api_key()


def test_api_key_from_config_file(sonos_home, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from sonos_tool import config
    config.save_config({"speaker": "X", "typesafe_api_key": "from-file"})
    assert jev.api_key() == "from-file"


def test_pick_builds_criteria_and_maps_position(sonos_home, key, monkeypatch):
    seen = {}

    def fake_ask(k, state, instructions, criteria):
        seen.update(key=k, state=state, instructions=instructions, criteria=criteria)
        return "2", 0.91, {"1": 0.07, "2": 0.91, "none": 0.02}

    monkeypatch.setattr(jev, "_ask", fake_ask)
    out = jev.pick("track", "live traveling alone jason isbell", ITEMS)
    assert out == {"position": 2, "confidence": 0.91, "probabilities": {"1": 0.07, "2": 0.91, "none": 0.02}}
    assert seen["key"] == "k-test"
    assert seen["state"]["request"] == "live traveling alone jason isbell"
    assert list(seen["criteria"]) == ["1", "2", "none"]
    assert seen["criteria"]["2"] == "Traveling Alone (Live) - Jason Isbell - Live from the Ryman"
    assert "track" in seen["instructions"]


def test_pick_none_gives_no_position(sonos_home, key, monkeypatch):
    monkeypatch.setattr(jev, "_ask", lambda *a: ("none", 0.6, {"1": 0.2, "2": 0.2, "none": 0.6}))
    assert jev.pick("album", "harvest neil young", ITEMS)["position"] is None


def test_pick_album_criteria_omit_album_column(sonos_home, key, monkeypatch):
    seen = {}
    monkeypatch.setattr(jev, "_ask", lambda k, s, i, c: (seen.update(c=c), ("1", 0.9, {}))[1])
    albums = [{"title": "Nebraska", "artist": "Bruce Springsteen", "album": "Nebraska", "item_id": "a", "uri": "u"}]
    jev.pick("album", "nebraska", albums)
    assert seen["c"]["1"] == "Nebraska - Bruce Springsteen"


def test_pick_wraps_sdk_errors(sonos_home, key, monkeypatch):
    class TypeSafeAuthenticationError(Exception):
        pass

    def boom(*a):
        raise TypeSafeAuthenticationError("401")

    monkeypatch.setattr(jev, "_ask", boom)
    with pytest.raises(SonosToolError, match="rejected the API key"):
        jev.pick("track", "x", ITEMS)

    def down(*a):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(jev, "_ask", down)
    with pytest.raises(SonosToolError, match="request failed"):
        jev.pick("track", "x", ITEMS)
