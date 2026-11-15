import pytest


@pytest.fixture(autouse=True)
def hive_home(tmp_path, monkeypatch):
    """Every test gets its own ~/.hive."""
    home = tmp_path / "hive-home"
    monkeypatch.setenv("HIVE_HOME", str(home))
    return home
