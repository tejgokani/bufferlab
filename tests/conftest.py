import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("BUFFERLAB_HOME", str(tmp_path / "home"))
