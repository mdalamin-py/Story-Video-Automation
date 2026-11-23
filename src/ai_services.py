"""Every AI service the studio can use, for the dashboard's Providers page.

Only says whether each one is set up (a key in .env, or the app installed) and which model it uses.
It never returns a key and never calls a service, so opening the page costs nothing."""
import os
import sys
from pathlib import Path

import story_ai


def _env(name):
    return os.environ.get(name, "").strip()


def _codex_installed():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.cinematic import codex_cli
    return bool(codex_cli())


def _row(group, ident, label, ready, model, use, how):
    return {"group": group, "id": ident, "label": label, "connected": bool(ready),
            "model": model or "Set in .env", "use": use, "setup": how}


def status():
    rows = []
    story_use = {"gemini": "Story plans · cheapest", "openai": "Story plans", "claude": "Story plans · best writing"}
    for item in story_ai.status():
        rows.append(_row("Story", item["id"], item["label"], item["connected"], item["model"],
                         story_use[item["id"]], story_ai.PRESETS[item["id"]]["key_env"]))
    rows.append(_row("Story", "codex", "Codex", _codex_installed(), _env("CODEX_MODEL") or "Codex default",
                     "Cinematic film scripts", "Install the Codex app and sign in, or set CODEX_PATH"))
    rows.append(_row("Video", "muse", "Muse Video", _env("MUSE_API_KEY"), "Muse video", "Video clips", "MUSE_API_KEY"))
    rows.append(_row("Video", "runway", "Runway", _env("RUNWAY_API_KEY"), _env("RUNWAY_VIDEO_MODEL") or "gen4.5",
                     "Video clips · Kling models too", "RUNWAY_API_KEY"))
    rows.append(_row("Images", "openai-images", "OpenAI images", _env("OPENAI_API_KEY"), _env("IMAGE_MODEL"),
                     "Illustrations", "OPENAI_API_KEY and IMAGE_MODEL"))
    rows.append(_row("Images", "vertex", "Google Vertex (Imagen)", _env("VERTEX_ACCESS_TOKEN") and _env("VERTEX_PROJECT"),
                     _env("IMAGE_MODEL"), "Illustrations", "VERTEX_ACCESS_TOKEN and VERTEX_PROJECT"))
    rows.append(_row("Voice", "edge", "Microsoft Edge voices", True, "38 languages", "Narration · free, no key", "Nothing to set"))
    rows.append(_row("Voice", "openai-speech", "OpenAI speech", _env("OPENAI_API_KEY"), _env("TTS_MODEL"),
                     "Narration", "OPENAI_API_KEY and TTS_MODEL"))
    rows.append(_row("Voice", "elevenlabs", "ElevenLabs", _env("ELEVENLABS_API_KEY"), _env("TTS_MODEL"),
                     "Narration · most natural", "ELEVENLABS_API_KEY"))
    return rows
