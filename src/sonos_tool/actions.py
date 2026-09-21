"""Sonos operations on top of SoCo.

Ported from the active section of sonos_mcp/sonos/sonos_actions.py with three
changes: nothing happens at import time, functions return data instead of
formatted strings, and the music service / speaker are resolved lazily.

Positions passed to Player methods are 0-indexed (SoCo's convention); the CLI
converts from the 1-indexed positions users see.
"""

from __future__ import annotations

import html
import os
import random
from time import sleep
from urllib.parse import quote, unquote, urlparse

import requests
import soco
from soco.data_structures import DidlMusicTrack
from soco.exceptions import MusicServiceAuthException, MusicServiceException, SoCoException, SoCoUPnPException
from soco.music_services import MusicService
from soco.music_services.token_store import JsonFileTokenStore

from . import config, store
from .didl import track_metadata
from .errors import AuthError, SonosToolError

# Amazon Music service id used in the soco:// URIs that Sonos hands back.
AMAZON_SID = 201
ENQUEUE_ATTEMPTS = 3


# --- music service search --------------------------------------------------

def _token_store():
    """SoCo's JSON token store; $SONOS_TOKEN_STORE overrides the default
    ~/.config/SoCo/token_store.json (used by tests and for isolation)."""
    override = os.environ.get("SONOS_TOKEN_STORE")
    return JsonFileTokenStore(override) if override else JsonFileTokenStore.from_config_file()


def music_service(device: soco.SoCo) -> MusicService:
    """The music service bound to the household of `device`.

    Binding to the configured speaker matters: SoCo otherwise talks through
    whichever speaker answered multicast first, and on a network with two Sonos
    households (S1 and S2) that changes from call to call. The authorization
    token is stored per household, so a random household means random 401s.
    A fresh instance is built per call so a token refreshed by another process
    is picked up.
    """
    return MusicService(config.music_service_name(), token_store=_token_store(), device=device)


def has_token(ms: MusicService, device: soco.SoCo) -> bool:
    return ms.auth_type not in ("DeviceLink", "AppLink") or ms.token_store.has_token(
        ms.service_id, device.household_id
    )


def _auth_hint(device: soco.SoCo) -> str:
    return (
        f"{config.music_service_name()} is not authorized for the Sonos household of "
        f"'{device.player_name}' on this machine. Run `sonos auth` once to link it."
    )


# Amazon's SMAPI endpoint occasionally answers 401 even with a valid token, so a
# search is retried with backoff before we call it an auth failure.
SEARCH_BACKOFF = (1, 2, 3)


def _raw_search(device: soco.SoCo, category: str, query: str, attempts: int = len(SEARCH_BACKOFF) + 1):
    """Run the music-service search, retrying on HTTP 401 with a reloaded token."""
    last: Exception | None = None
    for attempt in range(attempts):
        ms = music_service(device)
        if not has_token(ms, device):
            raise AuthError(_auth_hint(device))
        try:
            return ms.search(category, query)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status != 401:
                raise SonosToolError(f"Music service HTTP error: {e}") from e
            last = e
            if attempt < attempts - 1:
                sleep(SEARCH_BACKOFF[min(attempt, len(SEARCH_BACKOFF) - 1)])
        except MusicServiceAuthException as e:
            last = e
            break
        except MusicServiceException as e:
            raise SonosToolError(f"Music service error: {e}") from e
    raise AuthError(
        f"{config.music_service_name()} rejected the request (authorization expired or "
        "temporarily unavailable). Retry in a minute; if it keeps failing, run `sonos auth` "
        "to re-link the service."
    ) from last


def begin_auth(device: soco.SoCo, attempts: int = 3) -> dict:
    """Start an AppLink/DeviceLink authorization. Returns {url, link_code, link_device_id, household}."""
    ms = music_service(device)
    if ms.auth_type not in ("DeviceLink", "AppLink"):
        raise SonosToolError(
            f"{config.music_service_name()} uses auth type {ms.auth_type}; no linking step is needed."
        )
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            url = ms.begin_authentication()  # sets ms.link_code / ms.link_device_id
            link_code, link_device_id = ms.link_code, ms.link_device_id
            return {
                "url": url,
                "link_code": link_code,
                "link_device_id": link_device_id,
                "household": device.household_id,
                "speaker": device.player_name,
            }
        except (requests.exceptions.HTTPError, MusicServiceException) as e:
            last = e
            if attempt < attempts - 1:
                sleep(1)
    raise SonosToolError(f"Could not start authorization with {config.music_service_name()}: {last}") from last


def complete_auth(device: soco.SoCo, pending: dict) -> None:
    if pending.get("household") != device.household_id:
        raise SonosToolError(
            "The pending authorization is for a different Sonos household than "
            f"'{device.player_name}'. Run `sonos auth` again."
        )
    ms = music_service(device)
    try:
        ms.complete_authentication(pending["link_code"], pending.get("link_device_id"))
    except (requests.exceptions.HTTPError, MusicServiceException, MusicServiceAuthException) as e:
        raise AuthError(
            f"Authorization not completed: {e}. Finish signing in at the link, then run "
            "`sonos auth --complete` again."
        ) from e


def search(device: soco.SoCo, kind: str, query: str) -> list[dict]:
    """Search the music service (bound to `device`'s household) for tracks or albums.

    Saves the results to ~/.sonos/search_results/<kind>_search.json so a later
    `queue add-*` / `playlist add --from-search` can refer to them by position.
    Each result: {title, artist, album, item_id, uri}. item_id is the URL-quoted
    service id (e.g. catalog%3Atrack%3Aasin%3AB002G3NK88); Sonos requires the DIDL
    item id and the enqueued URI to use the same encoding.
    """
    category = {"track": "tracks", "album": "albums"}[kind]
    results = _raw_search(device, category, query)

    items: list[dict] = []
    if kind == "track":
        for track in results:
            meta = track.metadata.get("track_metadata")
            inner = meta.metadata if meta is not None and meta.metadata else {}
            items.append(
                {
                    "title": track.title,
                    "artist": inner.get("artist", "Unknown Artist"),
                    "album": inner.get("album", ""),
                    "item_id": quote(track.metadata.get("id", ""), safe=""),
                    # the uri contains '&sn=0' which must be entity-escaped inside DIDL
                    "uri": html.escape(track.uri),
                }
            )
    else:
        for album in results:
            meta = album.metadata
            title = meta.get("title", "Unknown Title")
            items.append(
                {
                    "title": title,
                    "artist": meta.get("artist", "Unknown Artist"),
                    "album": title,
                    "item_id": quote(meta.get("id", ""), safe=""),
                    "uri": album.uri,
                }
            )

    store.save_search(kind, items)
    return items


# --- player ------------------------------------------------------------------


class Player:
    """All operations against one Sonos speaker (the group coordinator)."""

    def __init__(self, device: soco.SoCo):
        self.device = device

    @property
    def name(self) -> str:
        return self.device.player_name

    # -- status / transport --------------------------------------------------

    def transport_state(self) -> str:
        return self.device.get_current_transport_info()["current_transport_state"]

    def status(self) -> dict:
        state = self.transport_state()
        info: dict = {
            "speaker": self.name,
            "state": state,
            "volume": self.device.volume,
            "muted": self.device.mute,
        }
        track = self.device.get_current_track_info()
        if track.get("title"):
            info.update(
                title=track.get("title", ""),
                artist=track.get("artist", ""),
                album=track.get("album", ""),
                position=track.get("position", ""),
                duration=track.get("duration", ""),
            )
            try:
                info["queue_position"] = int(track.get("playlist_position") or 0)
            except ValueError:
                info["queue_position"] = 0
        return info

    def play(self) -> None:
        try:
            self.device.play()
        except SoCoUPnPException:
            # Nothing loaded in the transport: start the queue from the top.
            self.device.play_from_queue(0)

    def pause(self) -> None:
        self.device.pause()

    def toggle(self) -> str:
        """Play if paused/stopped, pause if playing. Returns the new state word."""
        if self.transport_state() == "PLAYING":
            self.pause()
            return "paused"
        self.play()
        return "playing"

    def next(self) -> None:
        self.device.next()

    def play_from_queue(self, index: int) -> None:
        """index is 0-based."""
        self.device.play_from_queue(index)

    # -- volume ----------------------------------------------------------------

    def _members(self):
        return self.device.group.members if self.device.group else [self.device]

    def volume(self) -> int:
        return self.device.volume

    def set_volume(self, level: int) -> None:
        level = max(0, min(100, level))
        for s in self._members():
            s.volume = level

    def adjust_volume(self, delta: int) -> int:
        for s in self._members():
            s.volume = max(0, min(100, s.volume + delta))
        return self.device.volume

    def set_mute(self, muted: bool) -> None:
        for s in self._members():
            s.mute = muted

    # -- queue -----------------------------------------------------------------

    def queue(self) -> list[dict]:
        items: list[dict] = []
        start = 0
        while True:
            page = self.device.get_queue(start=start, max_items=200)
            for t in page:
                if isinstance(t, DidlMusicTrack):
                    items.append({"title": t.title, "artist": t.creator or "", "album": t.album or ""})
                else:
                    md = getattr(t, "metadata", {}) or {}
                    items.append({"title": md.get("title", getattr(t, "title", "")), "artist": "", "album": ""})
            start += len(page)
            if len(page) == 0 or start >= (page.total_matches or 0):
                break
        return items

    def queue_length(self) -> int:
        return self.device.get_queue(start=0, max_items=1).total_matches or 0

    def clear_queue(self) -> None:
        self.device.clear_queue()

    def remove_from_queue(self, index: int) -> None:
        """index is 0-based."""
        self.device.remove_from_queue(index)

    def enqueue(self, item: dict) -> tuple[int, int]:
        """Add a search-result / playlist entry to the end of the queue.

        Returns (first_position_1_indexed, number_of_tracks_added). Albums expand
        to all their tracks; single tracks return count 1.
        """
        metadata = track_metadata(item["item_id"], item["uri"])
        args = [
            ("InstanceID", 0),
            ("EnqueuedURI", item["uri"]),
            ("EnqueuedURIMetaData", metadata),
            ("DesiredFirstTrackNumberEnqueued", 0),
            ("EnqueueAsNext", 1),
        ]
        # The speaker validates the item with the music service; that lookup
        # intermittently fails with UPnP error 800, so retry briefly before giving up.
        for attempt in range(ENQUEUE_ATTEMPTS):
            try:
                response = self.device.avTransport.AddURIToQueue(args)
                break
            except SoCoUPnPException as e:
                if attempt == ENQUEUE_ATTEMPTS - 1 or str(e.error_code) not in ("800", "804"):
                    raise SonosToolError(f"Sonos refused to enqueue '{item.get('title')}': {e}") from e
                sleep(1)
        first = int(response.get("FirstTrackNumberEnqueued", 0))
        count = int(response.get("NumTracksAdded", 1) or 1)
        return first, count

    def enqueue_search_results(self, kind: str, positions: list[int]) -> list[tuple[dict, int, int]]:
        """Enqueue the 1-indexed positions from the last <kind> search.

        Returns [(item, first_position, count), ...] in the order added.
        """
        added = []
        for item in store.pick_search_results(kind, positions):
            first, count = self.enqueue(item)
            added.append((item, first, count))
        return added

    def enqueue_playlist(self, name: str, shuffle: bool = False) -> tuple[int, int]:
        """Add every track of a local playlist. Returns (first_position, count)."""
        tracks = store.load_playlist(name)
        if not tracks:
            raise SonosToolError(f"Playlist '{name}' is empty.")
        if shuffle:
            tracks = tracks[:]
            random.shuffle(tracks)
        first = 0
        total = 0
        for t in tracks:
            pos, count = self.enqueue(t)
            if first == 0:
                first = pos
            total += count
        return first, total

    # -- local playlists that need the speaker -----------------------------------

    def queue_item_as_playlist_entry(self, index: int) -> dict:
        """Convert queue entry at 0-based index into a storable playlist entry."""
        page = self.device.get_queue(start=index, max_items=1)
        if len(page) == 0:
            raise SonosToolError(f"Queue position {index + 1} is out of range.")
        track = page[0]
        uri = track.get_uri() if hasattr(track, "get_uri") else ""
        if not uri:
            raise SonosToolError("That queue entry has no URI and cannot be saved to a playlist.")
        return playlist_entry_from_queue_uri(
            uri,
            title=track.title,
            artist=getattr(track, "creator", "") or "",
            album=getattr(track, "album", "") or "",
        )

    # -- native Sonos playlists ------------------------------------------------

    def native_playlists(self) -> list[str]:
        return [p.title for p in self.device.get_sonos_playlists()]

    def create_native_playlist_from_local(self, local_name: str, native_name: str | None = None) -> str:
        """Build a native Sonos playlist from a local one via the queue; restores the queue after."""
        tracks = store.load_playlist(local_name)
        if not tracks:
            raise SonosToolError(f"Playlist '{local_name}' is empty.")
        target = native_name or local_name
        if target in self.native_playlists():
            raise SonosToolError(
                f"Native Sonos playlist '{target}' already exists. Choose another name with --as."
            )
        original_queue = list(self.device.get_queue(start=0, max_items=1000))
        try:
            self.device.clear_queue()
            for t in tracks:
                self.enqueue(t)
            self.device.create_sonos_playlist_from_queue(target)
        finally:
            try:
                self.device.clear_queue()
                for item in original_queue:
                    self.device.add_to_queue(item)
            except SoCoException:
                pass
        return target


# --- playlist helpers that do not need a speaker -----------------------------


def playlist_entry_from_queue_uri(uri: str, title: str, artist: str, album: str) -> dict:
    """Rebuild the search-style {item_id, uri} pair from a queued track's playback URI.

    Queued Amazon tracks look like
        x-sonos-http:catalog%3atrack%3aasin%3aB002G3NK88.mpd?sid=201&flags=40&sn=2   (current)
        x-sonos-http:catalog/tracks/B01MQYJR6J/xyz.mp4?sid=201&flags=...            (older ids)
    and must be re-enqueued as
        id  = 0fffffff<quoted id>            e.g. 0fffffffcatalog%3Atrack%3Aasin%3AB002G3NK88
        uri = soco://0fffffff<quoted id, quoted again>?sid=201&amp;sn=0
    which is exactly what the music-service search returns for the same track.
    """
    path = urlparse(unquote(uri)).path
    if "/" in path:
        # old style: the id is the directory, e.g. catalog/tracks/B01MQYJR6J/
        item_id = os.path.dirname(path) + "/"
        soco_uri = f"soco://0fffffff{item_id}?sid={AMAZON_SID}&amp;sn=0"
    else:
        raw_id = path.rsplit(".", 1)[0] if "." in path else path
        item_id = quote(raw_id, safe="")
        soco_uri = f"soco://0fffffff{quote(item_id, safe='')}?sid={AMAZON_SID}&amp;sn=0"
    return {"title": title, "artist": artist, "album": album, "item_id": item_id, "uri": soco_uri}


def add_search_result_to_playlist(name: str, position: int) -> tuple[dict, int]:
    """Copy 1-indexed track-search result into a local playlist. Returns (entry, new_length)."""
    (item,) = store.pick_search_results("track", [position])
    length = store.append_to_playlist(name, item)
    return item, length


def remove_from_playlist(name: str, position: int) -> dict:
    tracks = store.load_playlist(name)
    if not 1 <= position <= len(tracks):
        raise SonosToolError(f"Position {position} is out of range; '{name}' has {len(tracks)} tracks.")
    removed = tracks.pop(position - 1)
    store.save_playlist(name, tracks)
    return removed
