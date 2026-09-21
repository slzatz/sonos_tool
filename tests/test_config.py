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
