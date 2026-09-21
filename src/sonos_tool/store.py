"""Runtime state under ~/.sonos.

Layout (unchanged from earlier generations of this tool so existing data keeps working):

    ~/.sonos/config.toml                     speaker + music service
    ~/.sonos/speaker_cache.json              {speaker_name: ip} to skip network discovery
    ~/.sonos/search_results/track_search.json  last track search
    ~/.sonos/search_results/album_search.json  last album search
    ~/.sonos/playlists/<name>                local playlists; the filename IS the playlist
                                             name (no extension); contents are a JSON list

Every search-result or playlist entry is a dict with keys
title, artist, album, item_id, uri.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .errors import NoSearchResults, SonosToolError

SEARCH_KINDS = ("track", "album")


def sonos_dir() -> Path:
    """Root of runtime state. Honors $SONOS_HOME for tests/relocation."""
    override = os.environ.get("SONOS_HOME")
    return Path(override) if override else Path.home() / ".sonos"


def config_path() -> Path:
    return sonos_dir() / "config.toml"


def speaker_cache_path() -> Path:
    return sonos_dir() / "speaker_cache.json"


def search_results_dir() -> Path:
    return sonos_dir() / "search_results"


def playlists_dir() -> Path:
    return sonos_dir() / "playlists"


def _read_json(path: Path, default):
    if not path.is_file():
        return default
    with path.open() as f:
        return json.load(f)


def _write_json(path: Path, data) -> None:
    """Atomic write: temp file in the same directory, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


# --- search results -------------------------------------------------------


def search_path(kind: str) -> Path:
    if kind not in SEARCH_KINDS:
        raise ValueError(f"unknown search kind {kind!r}")
    return search_results_dir() / f"{kind}_search.json"


def save_search(kind: str, items: list[dict]) -> None:
    _write_json(search_path(kind), items)


def load_search(kind: str) -> list[dict]:
    items = _read_json(search_path(kind), None)
    if not items:
        raise NoSearchResults(
            f"No {kind} search results found. Run `sonos search {kind} QUERY` first."
        )
    return items


def pick_search_results(kind: str, positions: list[int]) -> list[dict]:
    """Return the entries at the given 1-indexed positions, validating range."""
    items = load_search(kind)
    picked = []
    for pos in positions:
        if not 1 <= pos <= len(items):
            raise SonosToolError(
                f"Position {pos} is out of range; the last {kind} search has {len(items)} results."
            )
        picked.append(items[pos - 1])
    return picked


# --- local playlists ------------------------------------------------------


def playlist_path(name: str) -> Path:
    if not name or "/" in name or name in (".", ".."):
        raise SonosToolError(f"Invalid playlist name {name!r}")
    return playlists_dir() / name


def list_playlists() -> list[str]:
    d = playlists_dir()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.endswith(".tmp"))


def load_playlist(name: str) -> list[dict]:
    path = playlist_path(name)
    if not path.is_file():
        raise SonosToolError(f"Playlist '{name}' not found. Run `sonos playlist list` to see playlists.")
    return _read_json(path, [])


def save_playlist(name: str, tracks: list[dict]) -> None:
    _write_json(playlist_path(name), tracks)


def append_to_playlist(name: str, track: dict) -> int:
    """Append a track (creating the playlist if needed). Returns the new length."""
    path = playlist_path(name)
    tracks = _read_json(path, []) if path.is_file() else []
    tracks.append(track)
    _write_json(path, tracks)
    return len(tracks)


# --- speaker cache ---------------------------------------------------------


def load_speaker_cache() -> dict[str, str]:
    return _read_json(speaker_cache_path(), {})


def save_speaker_cache(cache: dict[str, str]) -> None:
    _write_json(speaker_cache_path(), cache)
