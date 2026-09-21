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
from soco.discovery import by_name, scan_network, scan_network_get_by_name

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


def _remember(name: str, device: soco.SoCo) -> soco.SoCo:
    cache = store.load_speaker_cache()
    cache[name] = device.ip_address
    store.save_speaker_cache(cache)
    return device


def connect_speaker(name: str, retries: int = 2) -> soco.SoCo:
    """Return a SoCo device for the named speaker, or raise SpeakerNotFound.

    Order: cached IP (instant) -> multicast discovery by name (fast, but only
    sees the household that answers first) -> subnet scan across all households.
    """
    device = _try_cached(name)
    if device is not None:
        return device
    for attempt in range(retries):
        device = by_name(name)
        if device is not None:
            return _remember(name, device)
        if attempt < retries - 1:
            sleep(0.5)
    device = scan_network_get_by_name(name, multi_household=True, **SCAN_KWARGS)
    if device is not None:
        return _remember(name, device)
    raise SpeakerNotFound(
        f"Could not find a Sonos speaker named '{name}' on the network. "
        "Run `sonos speakers` to see available players."
    )


# Sonos S1 (legacy app) firmware stopped in the 57.x line; S2 is 60+.
S2_MIN_SOFTWARE_MAJOR = 60

# Subnet scan settings: 0.3 s per probe with many threads covers a /24 in ~1-2 s.
SCAN_KWARGS = {"max_threads": 128, "scan_timeout": 0.3}


def generation(software_version: str) -> str:
    """'S1' or 'S2' from a speaker's software_version string like '97.1-80312'."""
    try:
        major = int(software_version.split(".")[0])
    except (ValueError, AttributeError):
        return "?"
    return "S2" if major >= S2_MIN_SOFTWARE_MAJOR else "S1"


def discover_speakers() -> list[dict]:
    """Every Sonos player on the LAN, across all households.

    Multicast discovery returns only the household that answers first, which on a
    network with both an S1 and an S2 system hides one of them. A subnet scan with
    multi_household=True finds every zone; multicast is the fallback if the scan
    comes back empty (e.g. an unusual netmask).

    Each entry: {name, ip, model, household, generation}, sorted by generation
    (S2 first) then name.
    """
    zones = scan_network(multi_household=True, **SCAN_KWARGS) or set()
    if not zones:
        zones = soco.discover(timeout=5) or set()
    out = []
    for z in zones:
        info = z.get_speaker_info()
        out.append(
            {
                "name": z.player_name,
                "ip": z.ip_address,
                "model": info.get("model_name", ""),
                "household": z.household_id,
                "generation": generation(info.get("software_version", "")),
            }
        )
    return sorted(out, key=lambda d: (d["generation"] != "S2", d["name"].lower()))
