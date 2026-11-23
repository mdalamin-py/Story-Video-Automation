"""Pick the AI that writes the story plan: one choice per video, no routing JSON needed.

  auto    the cheapest connected AI first (Gemini, then OpenAI, then Claude), next one on failure
  openai  OpenAI Responses API (OPENAI_MODEL, default gpt-5-mini)
  gemini  Gemini through its OpenAI-compatible API (GEMINI_STORY_MODEL, default gemini-2.5-flash)
  claude  Claude through the Anthropic SDK (CLAUDE_STORY_MODEL, default claude-opus-5-5)

An AI counts as connected when its API key is set in .env. Every plan is cached by brief, so
choosing the same AI for the same brief again costs nothing.
"""
import os
from urllib.error import URLError

from pydantic import ValidationError

CHOICES = ("auto", "openai", "claude", "gemini")
AUTO_ORDER = ("gemini", "openai", "claude")          # cheapest first
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

PRESETS = {
    "gemini": {"label": "Gemini", "key_env": "GEMINI_API_KEY", "model_env": "GEMINI_STORY_MODEL",
               "model": "gemini-2.5-flash", "cost": "lowest"},
    "openai": {"label": "OpenAI", "key_env": "OPENAI_API_KEY", "model_env": "OPENAI_MODEL",
               "model": "gpt-5-mini", "cost": "low"},
    "claude": {"label": "Claude", "key_env": "ANTHROPIC_API_KEY", "model_env": "CLAUDE_STORY_MODEL",
               "model": "claude-opus-5-5", "cost": "higher"},
}


def model_for(name):
    preset = PRESETS[name]
    return os.environ.get(preset["model_env"], "").strip() or preset["model"]


def connected(name):
    return bool(os.environ.get(PRESETS[name]["key_env"], "").strip())


def status():
    """What the dashboard shows: never a key, only whether one is set."""
    return [{"id": name, "label": PRESETS[name]["label"], "model": model_for(name),
             "connected": connected(name), "cost": PRESETS[name]["cost"]} for name in AUTO_ORDER]


def candidates(choice):
    if choice not in CHOICES:
        raise ValueError("story_ai must be auto, openai, claude or gemini.")
    if choice == "auto":
        names = [name for name in AUTO_ORDER if connected(name)]
        if not names:
            raise ValueError("Connect a story AI: set GEMINI_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY in .env.")
        return names
    if not connected(choice):
        raise ValueError(f"{PRESETS[choice]['label']} is not connected: set {PRESETS[choice]['key_env']} in .env.")
    return [choice]


def _openai(brief, instructions):
    from providers import story_plan
    if os.environ.get("STORY_BUDGET_USD", "").strip():
        raise ValueError("STORY_BUDGET_USD needs a routed provider (Gemini or STORY_PROVIDER_CONFIG).")
    return story_plan(brief, model=model_for("openai"))


def _gemini(brief, instructions):
    from provider_router import Routing, generate_story
    routing = Routing.model_validate({"policy": "manual", "manual_provider": "gemini", "fallback": False,
        "max_estimated_usd": 0.05, "providers": [{"name": "gemini", "base_url": GEMINI_URL, "model": model_for("gemini"),
        "key_env": "GEMINI_API_KEY", "estimated_usd": 0.01, "token_limit": 8192, "reasoning_effort": "low"}]})
    return generate_story(routing, brief, instructions)


def _claude(brief, instructions):
    from claude_story import claude_story
    from provider_router import Story
    from providers import cached_story, save_story, story_cache_path
    if os.environ.get("STORY_BUDGET_USD", "").strip():
        raise ValueError("STORY_BUDGET_USD needs a routed provider (Gemini or STORY_PROVIDER_CONFIG).")
    cache = story_cache_path("claude", model_for("claude"), instructions, brief)
    if (plan := cached_story(cache)) is not None:
        return plan
    plan = Story.model_validate(claude_story(brief, instructions)).model_dump()
    save_story(cache, plan)
    return plan


RUNNERS = {"openai": _openai, "gemini": _gemini, "claude": _claude}


def generate(brief, instructions):
    """Plan with the brief's chosen AI; on auto, fall through to the next connected AI on failure."""
    choice = brief.get("story_ai", "auto")
    request = {key: value for key, value in brief.items() if key != "story_ai"}
    names, failures = candidates(choice), []
    for name in names:
        try:
            plan = RUNNERS[name](request, instructions)
            if len(plan["scenes"]) != brief["scene_count"]:
                raise ValueError("scene count mismatch")
            print(f"Story AI: {PRESETS[name]['label']} ({model_for(name)})", flush=True)
            return plan
        except (RuntimeError, ValueError, ValidationError, KeyError, URLError, TimeoutError) as exc:
            failures.append(f"{PRESETS[name]['label']}: {exc}")
            if choice != "auto":
                break
    raise RuntimeError("No story AI completed the plan. " + "; ".join(failures))
