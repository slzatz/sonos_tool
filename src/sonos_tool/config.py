"""Configuration and speaker resolution.

Speaker name precedence: --speaker flag > $SONOS_SPEAKER > ~/.sonos/config.toml.
Connecting to the speaker first tries the IP cached in ~/.sonos/speaker_cache.json
(instant), and only falls back to SSDP discovery by name (1-3 s) if the cache is
missing or stale.
"""

from __future__ import annotations

import os
import tomllib
from time import sleep

import soco
from soco.discovery import by_name

from . import store
from .errors import ConfigError, SpeakerNotFound

DEFAULT_MUSIC_SERVICE = "Amazon Music"


def load_config() -> dict:
    path = store.config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Could not parse {path}: {e}") from e


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_config(cfg: dict) -> None:
    path = store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key} = {_toml_str(str(value))}" for key, value in cfg.items()]
    path.write_text("\n".join(lines) + "\n")


def resolve_speaker_name(flag: str | None = None) -> str:
    if flag:
        return flag
    env = os.environ.get("SONOS_SPEAKER")
    if env:
        return env
    cfg = load_config()
    name = cfg.get("speaker")
    if name:
        return name
    raise ConfigError(
        "No speaker configured. Run `sonos speakers` to list players, then "
        '`sonos speaker set "Name"` (or pass --speaker / set $SONOS_SPEAKER).'
    )


def music_service_name() -> str:
    return os.environ.get("SONOS_MUSIC_SERVICE") or load_config().get("music_service") or DEFAULT_MUSIC_SERVICE


def set_default_speaker(name: str) -> None:
    cfg = load_config()
    cfg["speaker"] = name
    cfg.setdefault("music_service", DEFAULT_MUSIC_SERVICE)
    save_config(cfg)


def _try_cached(name: str) -> soco.SoCo | None:
    ip = store.load_speaker_cache().get(name)
    if not ip:
        return None
    try:
        device = soco.SoCo(ip)
        if device.player_name == name:
            return device
    except Exception:
        pass
    return None


def connect_speaker(name: str, retries: int = 3) -> soco.SoCo:
    """Return a SoCo device for the named speaker, or raise SpeakerNotFound."""
    device = _try_cached(name)
    if device is not None:
        return device
    for attempt in range(retries):
        device = by_name(name)
        if device is not None:
            cache = store.load_speaker_cache()
            cache[name] = device.ip_address
            store.save_speaker_cache(cache)
            return device
        if attempt < retries - 1:
            sleep(1)
    raise SpeakerNotFound(
        f"Could not find a Sonos speaker named '{name}' on the network. "
        "Run `sonos speakers` to see available players."
    )


def discover_speakers(timeout: float = 5.0) -> list[soco.SoCo]:
    """All Sonos players on the LAN, sorted by name."""
    found = soco.discover(timeout=timeout) or set()
    return sorted(found, key=lambda d: d.player_name.lower())
