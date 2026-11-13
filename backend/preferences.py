"""Nonsecret provider preferences captured when a studio job is queued."""
from contextlib import closing

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_provider: Literal["muse-video.com", "runway"] | None = None
    video_fallback: Literal["muse-video.com", "runway"] | None = None
    tts_provider: Literal["openai", "elevenlabs"] | None = None

    story_budget_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    def environment(self):
        keys = {"video_provider": "VIDEO_PROVIDER", "video_fallback": "VIDEO_FALLBACK_PROVIDER",
                "tts_provider": "TTS_PROVIDER", "story_budget_usd": "STORY_BUDGET_USD"}
        return {keys[name]: str(value) for name, value in self.model_dump(exclude_none=True).items()}


def read_preferences(db):
    row = db.execute("SELECT value FROM preferences WHERE id=1").fetchone()
    return Preferences.model_validate_json(row[0]) if row else Preferences()


def get_preferences():
    from backend.jobs import connect

    with closing(connect()) as db:
        return read_preferences(db)


def save_preferences(preferences):
    from backend.jobs import connect

    with closing(connect()) as db:
        db.execute("INSERT INTO preferences(id,value) VALUES(1,?) "
                   "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                   (preferences.model_dump_json(),))
