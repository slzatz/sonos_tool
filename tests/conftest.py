import pytest


@pytest.fixture
def sonos_home(tmp_path, monkeypatch):
    """Point all runtime state at a temp dir and clear speaker env overrides."""
    home = tmp_path / ".sonos"
    monkeypatch.setenv("SONOS_HOME", str(home))
    monkeypatch.delenv("SONOS_SPEAKER", raising=False)
    monkeypatch.delenv("SONOS_MUSIC_SERVICE", raising=False)
    return home
