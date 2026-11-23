import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import story_ai
from claude_story import StoryOutput, claude_story

PLAN = {"title": "T", "description": "D", "story": "S", "scenes": [{"visual_prompt": "Rain", "dialogue": "", "caption": ""}]}
BRIEF = {"story": "s", "scene_count": 1}
KEYS = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "STORY_BUDGET_USD")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_status_shows_connection_never_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-value")
    rows = {row["id"]: row for row in story_ai.status()}
    assert rows["claude"]["connected"] and not rows["gemini"]["connected"]
    assert rows["claude"]["model"] == "claude-opus-5-5"
    assert "secret-value" not in json.dumps(story_ai.status())


def test_auto_uses_cheapest_connected_and_falls_through_on_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g"); monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert story_ai.candidates("auto") == ["gemini", "claude"]
    calls = []
    def gemini(brief, instructions):
        calls.append(("gemini", brief)); raise RuntimeError("HTTP 503")
    def claude(brief, instructions):
        calls.append(("claude", brief)); return PLAN
    with patch.dict(story_ai.RUNNERS, {"gemini": gemini, "claude": claude}):
        assert story_ai.generate({**BRIEF, "story_ai": "auto"}, "x") == PLAN
    assert [name for name, _ in calls] == ["gemini", "claude"]
    assert all("story_ai" not in brief for _, brief in calls)      # the choice never reaches the model


def test_explicit_choice_does_not_fall_through_and_names_the_missing_key(monkeypatch):
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        story_ai.candidates("claude")
    monkeypatch.setenv("GEMINI_API_KEY", "g"); monkeypatch.setenv("OPENAI_API_KEY", "o")
    with patch.dict(story_ai.RUNNERS, {"gemini": MagicMock(side_effect=RuntimeError("down")), "openai": MagicMock(return_value=PLAN)}):
        with pytest.raises(RuntimeError, match="Gemini: down"):
            story_ai.generate({**BRIEF, "story_ai": "gemini"}, "x")
        story_ai.RUNNERS["openai"].assert_not_called()
    with pytest.raises(ValueError, match="story_ai must be"):
        story_ai.candidates("chatgpt")


def test_gemini_preset_uses_its_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    reply = {"choices": [{"message": {"content": json.dumps(PLAN)}}]}
    with patch("provider_router.request", return_value=(reply, {})) as api:
        assert story_ai._gemini(BRIEF, "x") == PLAN
    url, _, key, payload = api.call_args.args
    assert url == story_ai.GEMINI_URL + "/chat/completions" and key == "g"
    assert payload["model"] == "gemini-2.5-flash" and payload["reasoning_effort"] == "low"


def parse_reply(stop_reason="end_turn", parsed=True):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=StoryOutput.model_validate(PLAN) if parsed else None)


def test_claude_request_uses_structured_output_and_refusal_fallback(monkeypatch):
    client = MagicMock()
    client.beta.messages.parse.return_value = parse_reply()
    assert claude_story(BRIEF, "instructions", client=client) == PLAN
    kwargs = client.beta.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["output_format"] is StoryOutput
    assert kwargs["output_config"] == {"effort": "medium"} and kwargs["system"] == "instructions"
    assert kwargs["fallbacks"] == "default" and kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    monkeypatch.setenv("CLAUDE_STORY_MODEL", "claude-haiku-5-5"); monkeypatch.setenv("CLAUDE_STORY_EFFORT", "low")
    claude_story(BRIEF, "instructions", client=client)
    kwargs = client.beta.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5" and kwargs["output_config"] == {"effort": "low"}


def test_claude_refusal_and_truncation_are_reported(monkeypatch):
    client = MagicMock()
    client.beta.messages.parse.return_value = parse_reply("refusal", parsed=False)
    with pytest.raises(RuntimeError, match="declined"):
        claude_story(BRIEF, "x", client=client)
    client.beta.messages.parse.return_value = parse_reply("max_tokens", parsed=False)
    with pytest.raises(RuntimeError, match="cut off"):
        claude_story(BRIEF, "x", client=client)


def test_claude_plan_is_cached(tmp_path, monkeypatch):
    import providers
    monkeypatch.setenv("STORY_CACHE", "1"); monkeypatch.setattr(providers, "STORY_CACHE", tmp_path)
    with patch("claude_story.claude_story", return_value=PLAN) as call:
        assert story_ai._claude(BRIEF, "x") == PLAN
        assert story_ai._claude(BRIEF, "x") == PLAN
    call.assert_called_once()


def test_brief_validation_accepts_only_known_story_ais():
    from main import validate
    brief = {"story": "s", "style": "c", "language": "bn", "scene_count": 1, "seconds_per_scene": 6, "resolution": "720p",
             "audio": True, "burn_captions": True, "made_for_kids": False, "synthetic_disclosure": False}
    validate({**brief, "story_ai": "claude"})
    with pytest.raises(ValueError, match="story_ai"):
        validate({**brief, "story_ai": "grok"})


def test_dashboard_endpoint_reports_story_ais_without_keys(monkeypatch):
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.api import app
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "t" * 32); monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini")
    client = TestClient(app)
    assert client.get("/api/story-ais").status_code == 401
    reply = client.get("/api/story-ais", headers={"Authorization": "Bearer " + "t" * 32})
    assert reply.status_code == 200 and "secret-gemini" not in reply.text
    assert {row["id"]: row["connected"] for row in reply.json()} == {"gemini": True, "openai": False, "claude": False}


def test_dashboard_lists_every_ai_service_without_keys(monkeypatch):
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.api import app
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "RUNWAY_API_KEY", "ELEVENLABS_API_KEY", "VERTEX_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "t" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini"); monkeypatch.setenv("MUSE_API_KEY", "secret-muse")
    client = TestClient(app)
    assert client.get("/api/ai-services").status_code == 401
    reply = client.get("/api/ai-services", headers={"Authorization": "Bearer " + "t" * 32})
    assert reply.status_code == 200 and "secret-" not in reply.text
    rows = {row["id"]: row for row in reply.json()}
    assert {"gemini", "openai", "claude", "codex", "muse", "runway", "openai-images", "vertex",
            "edge", "openai-speech", "elevenlabs"} <= set(rows)
    assert rows["muse"]["connected"] and not rows["runway"]["connected"] and rows["edge"]["connected"]
    assert rows["runway"]["setup"] == "RUNWAY_API_KEY"
