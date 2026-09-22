"""CLI tests with the speaker layer replaced by a fake; no network."""

import json

import pytest
from click.testing import CliRunner

from sonos_tool import actions, cli, config, store

TRACKS = [
    {"title": "Heart of Gold", "artist": "Neil Young", "album": "Harvest", "item_id": "a/", "uri": "soco://a"},
    {"title": "Heart of Gold (Live)", "artist": "Neil Young", "album": "Live at Massey Hall", "item_id": "b/", "uri": "soco://b"},
]


class FakeDevice:
    player_name = "Fake Room"
    household_id = "Sonos_FAKE"


class FakePlayer:
    def __init__(self):
        self.name = "Fake Room"
        self.device = FakeDevice()
        self.q = [{"title": "Existing", "artist": "Someone", "album": "Album"}]
        self.vol = 30
        self.played = None
        self.state = "PAUSED_PLAYBACK"

    def status(self):
        return {"speaker": self.name, "state": self.state, "volume": self.vol, "muted": False,
                "title": "Existing", "artist": "Someone", "album": "Album", "position": "0:00:01",
                "duration": "0:03:00", "queue_position": 1}

    def queue(self):
        return [dict(t) for t in self.q]

    def queue_length(self):
        return len(self.q)

    def enqueue_search_results(self, kind, positions):
        out = []
        for item in store.pick_search_results(kind, positions):
            self.q.append({"title": item["title"], "artist": item["artist"], "album": item["album"]})
            out.append((item, len(self.q), 1))
        return out

    def play_from_queue(self, index):
        self.played = index

    def volume(self):
        return self.vol

    def set_volume(self, level):
        self.vol = level

    def adjust_volume(self, delta):
        self.vol = max(0, min(100, self.vol + delta))
        return self.vol

    def remove_from_queue(self, index):
        self.q.pop(index)

    def pause(self):
        self.state = "PAUSED_PLAYBACK"


@pytest.fixture
def fake(sonos_home, monkeypatch):
    player = FakePlayer()
    monkeypatch.setattr(cli.Context, "player", lambda self: player)
    return player


def run(*args):
    return CliRunner(mix_stderr=False).invoke(cli.cli, list(args)) if "mix_stderr" in CliRunner.__init__.__code__.co_varnames else CliRunner().invoke(cli.cli, list(args))


def test_help_lists_commands():
    r = run("--help")
    assert r.exit_code == 0
    for word in ("search", "queue", "playlist", "volume", "speakers"):
        assert word in r.output


def test_search_then_add_track_with_play(fake, monkeypatch):
    monkeypatch.setattr(actions, "search", lambda device, kind, q: (store.save_search(kind, TRACKS), TRACKS)[1])
    r = run("search", "track", "heart", "of", "gold")
    assert r.exit_code == 0
    assert "1. Heart of Gold - Neil Young - Harvest" in r.output
    assert "position 1 is not always" in r.output

    r = run("queue", "add-track", "2", "--play")
    assert r.exit_code == 0, r.output
    assert "Added 'Heart of Gold (Live)' by Neil Young at queue position 2" in r.output
    assert fake.played == 1  # 0-indexed


def test_add_track_out_of_range(fake):
    store.save_search("track", TRACKS)
    r = run("queue", "add-track", "5")
    assert r.exit_code == 1
    assert "out of range" in (r.stderr if hasattr(r, "stderr") and r.stderr else r.output)


def test_add_without_search(fake):
    r = run("queue", "add-album", "1")
    assert r.exit_code == 1
    assert "sonos search album" in (r.stderr if hasattr(r, "stderr") and r.stderr else r.output)


def test_queue_json_marks_playing(fake):
    r = run("--json", "queue")
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data[0]["position"] == 1 and data[0]["playing"] is True


def test_volume_forms(fake):
    assert "Volume 30" in run("volume").output
    assert "Volume 45" in run("volume", "45").output
    assert "Volume 40" in run("volume", "down", "5").output
    assert "Volume 50" in run("volume", "up").output
    assert run("volume", "150").exit_code == 1
    assert run("volume", "sideways").exit_code == 1


def test_play_position_validated(fake):
    r = run("play", "7")
    assert r.exit_code == 1
    r = run("play", "1")
    assert r.exit_code == 0 and fake.played == 0


def test_queue_remove_converts_index(fake):
    fake.q.append({"title": "Second", "artist": "", "album": ""})
    r = run("queue", "remove", "2")
    assert r.exit_code == 0 and "Removed Second" in r.output
    assert len(fake.q) == 1


def test_playlist_add_from_search_and_show(fake):
    store.save_search("track", TRACKS)
    r = run("playlist", "add", "mix", "--from-search", "1")
    assert r.exit_code == 0 and "1 tracks" in r.output
    r = run("playlist", "show", "mix")
    assert "Heart of Gold - Neil Young - Harvest" in r.output
    r = run("playlist", "add", "mix")
    assert r.exit_code == 1  # neither option given
    r = run("playlist", "remove", "mix", "1")
    assert r.exit_code == 0
    assert store.load_playlist("mix") == []


def test_config_error_exit_code(sonos_home):
    # real Context.player -> no speaker configured -> ConfigError exit 3
    r = run("status")
    assert r.exit_code == 3


def test_search_parses_and_quotes_amazon_ids(sonos_home, monkeypatch):
    """Amazon ids contain ':'; the stored item_id must be URL-quoted to match the URI."""
    class TM:
        metadata = {"artist": "Neil Young"}

    class Track:
        title = "Heart Of Gold"
        uri = "soco://0fffffffcatalog%253Atrack%253Aasin%253AB002G3NK88?sid=201&sn=0"
        metadata = {"id": "catalog:track:asin:B002G3NK88", "track_metadata": TM()}

    class FakeMS:
        auth_type = "Anonymous"

        def __init__(self, name, token_store=None, device=None):
            pass

        def search(self, category, query):
            assert category == "all"
            return [Track()]

    monkeypatch.setattr(actions, "MusicService", FakeMS)
    items = actions.search(object(), "track", "heart of gold")
    assert items[0]["item_id"] == "catalog%3Atrack%3Aasin%3AB002G3NK88"
    assert items[0]["uri"].endswith("?sid=201&amp;sn=0")
    assert items[0]["album"] == ""
    assert store.load_search("track") == items


def _fake_ms(results):
    """A MusicService stand-in whose universal search returns `results`."""
    class FakeMS:
        auth_type = "Anonymous"

        def __init__(self, name, token_store=None, device=None):
            pass

        def search(self, category, query):
            assert category == "all"
            return results

    return FakeMS


class _Item:
    """Stands in for an MSTrack / MSAlbum / MSArtist from a universal search."""

    def __init__(self, item_id, title, uri, artist=None, track_metadata=False):
        self.title = title
        self.uri = uri
        self.metadata = {"id": item_id, "title": title}
        if artist is not None and not track_metadata:
            self.metadata["artist"] = artist
        if track_metadata:
            inner = type("TM", (), {"metadata": {"artist": artist}})()
            self.metadata["track_metadata"] = inner


def test_search_track_drops_podcast_episodes(sonos_home, monkeypatch):
    """Podcast episodes come back from the universal search as tracks; drop them."""
    song = _Item("catalog:track:asin:B002G3NK88", "Heart Of Gold",
                 "soco://0fffffffcatalog%253Atrack%253Aasin%253AB002G3NK88?sid=201&sn=0",
                 artist="Neil Young", track_metadata=True)
    episode = _Item("podcast:episode:uuid:3ce17591", "A Heart Of Gold | With Ruth Negga",
                    "soco://0fffffffpodcast%253Aepisode%253Auuid%253A3ce17591?sid=201&sn=0",
                    artist=None, track_metadata=True)

    monkeypatch.setattr(actions, "MusicService", _fake_ms([episode, song, episode]))
    items = actions.search(object(), "track", "heart of gold")
    assert [i["title"] for i in items] == ["Heart Of Gold"]
    assert items[0]["artist"] == "Neil Young"
    assert store.load_search("track") == items


def test_search_album_keeps_only_albums(sonos_home, monkeypatch):
    """A universal search mixes artists and playlists in; only albums survive."""
    album = _Item("catalog:album:asin:B00138GZ5W", "Nebraska",
                  "x-rincon-cpcontainer:0fffffffcatalog%3Aalbum%3Aasin%3AB00138GZ5W",
                  artist="Bruce Springsteen")
    artist = _Item("catalog:artist:asin:B000QJJ", "Bruce Springsteen",
                   "x-rincon-cpcontainer:0fffffffcatalog%3Aartist%3Aasin%3AB000QJJ")
    playlist = _Item("catalog:playlist:asin:B0CXC", "Springsteen Essentials",
                     "x-rincon-cpcontainer:0fffffffcatalog%3Aplaylist%3Aasin%3AB0CXC")

    monkeypatch.setattr(actions, "MusicService", _fake_ms([artist, playlist, album]))
    items = actions.search(object(), "album", "nebraska springsteen")
    assert len(items) == 1
    assert items[0]["title"] == items[0]["album"] == "Nebraska"
    assert items[0]["artist"] == "Bruce Springsteen"
    assert items[0]["item_id"] == "catalog%3Aalbum%3Aasin%3AB00138GZ5W"
    # container URIs are enqueued as-is; only track URIs get HTML-escaped
    assert items[0]["uri"] == album.uri
    assert store.load_search("album") == items


def test_album_title_not_printed_twice():
    """Album search results carry album == title; the line must not repeat it."""
    assert cli._fmt_track(
        {"title": "Nebraska", "artist": "Bruce Springsteen", "album": "Nebraska"}
    ) == "Nebraska - Bruce Springsteen"
    # a track whose album genuinely differs still shows all three
    assert cli._fmt_track(
        {"title": "Atlantic City", "artist": "Bruce Springsteen", "album": "Nebraska"}
    ) == "Atlantic City - Bruce Springsteen - Nebraska"


def test_search_retries_401_then_auth_error(sonos_home, monkeypatch):
    import requests

    calls = {"n": 0}

    class FakeMS:
        auth_type = "Anonymous"

        def __init__(self, name, token_store=None, device=None):
            pass

        def search(self, category, query):
            calls["n"] += 1
            resp = requests.Response()
            resp.status_code = 401
            raise requests.exceptions.HTTPError(response=resp)

    monkeypatch.setattr(actions, "MusicService", FakeMS)
    monkeypatch.setattr(actions, "sleep", lambda s: None)
    from sonos_tool.errors import AuthError
    with pytest.raises(AuthError, match="authorization expired|temporarily unavailable"):
        actions.search(object(), "album", "x")
    assert calls["n"] == len(actions.SEARCH_BACKOFF) + 1


def test_playlist_entry_from_queue_uri_new_and_old_formats():
    new = actions.playlist_entry_from_queue_uri(
        "x-sonos-http:catalog%3atrack%3aasin%3aB002G3NK88.mpd?sid=201&flags=40&sn=2", "T", "A", "")
    assert new["item_id"] == "catalog%3Atrack%3Aasin%3AB002G3NK88"
    assert new["uri"] == "soco://0fffffffcatalog%253Atrack%253Aasin%253AB002G3NK88?sid=201&amp;sn=0"
    old = actions.playlist_entry_from_queue_uri(
        "x-sonos-http:catalog/tracks/B01MQYJR6J/song.mp4?sid=201&flags=8224&sn=2", "T", "A", "Al")
    assert old["item_id"] == "catalog/tracks/B01MQYJR6J/"
    assert old["uri"] == "soco://0fffffffcatalog/tracks/B01MQYJR6J/?sid=201&amp;sn=0"



def test_search_without_token_fails_fast(sonos_home, monkeypatch):
    class Store:
        def has_token(self, sid, hh):
            return False

    class FakeMS:
        auth_type = "AppLink"
        service_id = 201

        def __init__(self, name, token_store=None, device=None):
            self.token_store = Store()

        def search(self, *a):
            raise AssertionError("search must not be attempted without a token")

    monkeypatch.setattr(actions, "MusicService", FakeMS)
    from sonos_tool.errors import AuthError
    with pytest.raises(AuthError, match="sonos auth"):
        actions.search(FakeDevice(), "track", "x")


def test_auth_two_step_flow(fake, monkeypatch):
    state = {}

    class Store:
        def has_token(self, sid, hh):
            return "token" in state

    class FakeMS:
        auth_type = "AppLink"
        service_id = 201

        def __init__(self, name, token_store=None, device=None):
            self.token_store = Store()

        def begin_authentication(self):
            self.link_code, self.link_device_id = "CODE123", "dev-1"
            return "https://amazon.example/link"

        def complete_authentication(self, link_code, link_device_id=None):
            assert (link_code, link_device_id) == ("CODE123", "dev-1")
            state["token"] = True

    monkeypatch.setattr(actions, "MusicService", FakeMS)
    r = run("auth", "--status")
    assert r.exit_code == 0 and "NOT authorized" in r.output
    r = run("auth")  # CliRunner stdin is not a tty -> two-step mode
    assert r.exit_code == 0, r.output
    assert "https://amazon.example/link" in r.output and "sonos auth --complete" in r.output
    assert store.load_pending_auth()["household"] == "Sonos_FAKE"
    r = run("auth", "--complete")
    assert r.exit_code == 0 and "Authorized" in r.output
    assert store.load_pending_auth() is None
    assert "authorized" in run("auth", "--status").output
    r = run("auth", "--complete")
    assert r.exit_code == 1  # nothing pending
