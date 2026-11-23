import pytest


@pytest.fixture(autouse=True)
def isolated_story_cache(monkeypatch):
    """Tests must never read or write the real runs/story-cache; cache tests opt back in."""
    monkeypatch.setenv("STORY_CACHE", "0")
