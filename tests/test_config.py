import pytest

from sonos_tool import config, store
from sonos_tool.errors import ConfigError


def test_no_config_raises(sonos_home):
    with pytest.raises(ConfigError, match="No speaker configured"):
        config.resolve_speaker_name()


def test_precedence_flag_env_file(sonos_home, monkeypatch):
    config.save_config({"speaker": "File Room", "music_service": "Amazon Music"})
    assert config.resolve_speaker_name() == "File Room"
    monkeypatch.setenv("SONOS_SPEAKER", "Env Room")
    assert config.resolve_speaker_name() == "Env Room"
    assert config.resolve_speaker_name("Flag Room") == "Flag Room"


def test_save_and_load_config_round_trip(sonos_home):
    config.set_default_speaker('Tom\'s "Reading" Room')
    cfg = config.load_config()
    assert cfg["speaker"] == 'Tom\'s "Reading" Room'
    assert cfg["music_service"] == config.DEFAULT_MUSIC_SERVICE
    assert store.config_path().is_file()


def test_bad_toml_raises(sonos_home):
    store.config_path().parent.mkdir(parents=True)
    store.config_path().write_text("speaker = \n")
    with pytest.raises(ConfigError, match="Could not parse"):
        config.load_config()


def test_generation_from_software_version():
    assert config.generation("57.23-74170") == "S1"
    assert config.generation("97.1-80312") == "S2"
    assert config.generation("") == "?"


def test_discover_speakers_groups_all_households(sonos_home, monkeypatch):
    class Zone:
        def __init__(self, name, ip, hh, sw, model):
            self.player_name, self.ip_address, self.household_id = name, ip, hh
            self._info = {"software_version": sw, "model_name": model}

        def get_speaker_info(self):
            return self._info

    zones = {
        Zone("Kitchen", "10.0.0.2", "Sonos_OLD", "57.23-74170", "Sonos Play:1"),
        Zone("Sitting Room", "10.0.0.9", "Sonos_NEW", "97.1-80312", "Sonos One SL"),
        Zone("Barn", "10.0.0.8", "Sonos_NEW", "97.1-80312", "Sonos Move"),
    }
    seen = {}
    monkeypatch.setattr(config, "scan_network", lambda **kw: seen.update(kw) or zones)
    monkeypatch.setattr(config.soco, "discover", lambda **kw: (_ for _ in ()).throw(AssertionError("fallback used")))
    out = config.discover_speakers()
    assert seen["multi_household"] is True
    assert [d["name"] for d in out] == ["Barn", "Sitting Room", "Kitchen"]  # S2 first, then S1
    assert out[0]["generation"] == "S2" and out[2]["generation"] == "S1"


def test_connect_speaker_falls_back_to_network_scan(sonos_home, monkeypatch):
    class Dev:
        player_name, ip_address = "Sitting Room", "10.0.0.9"

    monkeypatch.setattr(config, "by_name", lambda name: None)
    monkeypatch.setattr(config, "sleep", lambda s: None)
    monkeypatch.setattr(config, "scan_network_get_by_name", lambda name, **kw: Dev() if name == "Sitting Room" else None)
    assert config.connect_speaker("Sitting Room").ip_address == "10.0.0.9"
    assert store.load_speaker_cache() == {"Sitting Room": "10.0.0.9"}
    from sonos_tool.errors import SpeakerNotFound
    with pytest.raises(SpeakerNotFound):
        config.connect_speaker("Nope")
