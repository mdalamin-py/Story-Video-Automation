import pytest


@pytest.fixture(autouse=True)
def isolated_story_cache(monkeypatch):
    """Tests must never read or write the real runs/story-cache; cache tests opt back in."""
    monkeypatch.setenv("STORY_CACHE", "0")


@pytest.fixture(autouse=True)
def isolated_env_file(monkeypatch, tmp_path):
    """Tests never read or change the real .env with your keys."""
    monkeypatch.setenv("STUDIO_RELOAD_ENV", "0")
    from backend import environment
    monkeypatch.setattr(environment, "ENV_FILE", tmp_path / "test.env")
