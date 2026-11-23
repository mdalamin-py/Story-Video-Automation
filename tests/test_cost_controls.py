"""Each saving must hold: nothing paid twice for the same work, nothing paid for work that will be rejected."""
import base64
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import providers
from image_provider import image_scene
from main import scene_asset_folders, legacy_asset_key
from speech import narration

BRIEF = {"story": "s", "scene_count": 1}
PLAN = {"title": "T", "description": "D", "story": "S", "scenes": [{"visual_prompt": "Rain", "dialogue": "", "caption": ""}]}


def completed(plan):
    return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(plan)}]}]}


def test_story_plan_is_cached_and_reasoning_is_kept_low(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_CACHE", "1"); monkeypatch.setattr(providers, "STORY_CACHE", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "k"); monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    with patch("providers.request", return_value=(completed(PLAN), {})) as api:
        assert providers.story_plan(BRIEF) == PLAN
        assert providers.story_plan(BRIEF) == PLAN          # second draft of the same brief: free
    api.assert_called_once()
    payload = api.call_args.args[3]
    assert payload["reasoning"] == {"effort": "low"} and payload["max_output_tokens"] == 6000
    with patch("providers.request", return_value=(completed(PLAN), {})) as api:
        providers.story_plan({**BRIEF, "story": "a different story"})
    api.assert_called_once()                                 # a changed brief is a new request


def test_non_reasoning_models_get_no_reasoning_field_and_truncation_is_explained(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    assert "reasoning" not in providers.story_payload(BRIEF)
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "extreme")
    with pytest.raises(ValueError, match="OPENAI_REASONING_EFFORT"):
        providers.story_payload(BRIEF)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT"); monkeypatch.setenv("OPENAI_API_KEY", "k")
    cut = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
    with patch("providers.request", return_value=(cut, {})):
        with pytest.raises(RuntimeError, match="OPENAI_MAX_OUTPUT_TOKENS"):
            providers.story_plan(BRIEF)


def test_router_reuses_any_providers_plan_and_sends_reasoning_effort(tmp_path, monkeypatch):
    from provider_router import generate_story, parse_routing
    monkeypatch.setenv("STORY_CACHE", "1"); monkeypatch.setattr(providers, "STORY_CACHE", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    routing = parse_routing(json.dumps({"policy": "lowest_cost", "max_estimated_usd": 0.1, "providers": [
        {"name": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash",
         "key_env": "GEMINI_API_KEY", "estimated_usd": 0.01, "reasoning_effort": "low"}]}))
    reply = {"choices": [{"message": {"content": json.dumps(PLAN)}}]}
    with patch("provider_router.request", return_value=(reply, {})) as api:
        assert generate_story(routing, BRIEF, "instructions") == PLAN
        assert generate_story(routing, BRIEF, "instructions") == PLAN
    api.assert_called_once()
    assert api.call_args.args[3]["reasoning_effort"] == "low"


def test_example_routing_tries_the_cheapest_provider_first():
    from provider_router import parse_routing
    example = Path(__file__).resolve().parents[1] / "input" / "story-providers.example.json"
    routing = parse_routing(example.read_text(encoding="utf-8"))
    assert routing.policy == "lowest_cost" and routing.candidates()[0].name == "gemini"


def test_gpt_image_quality_defaults_to_medium(tmp_path, monkeypatch):
    image = b"\x89PNG\r\n\x1a\n" + b"x"
    reply = {"data": [{"b64_json": base64.b64encode(image).decode()}]}
    with patch("image_provider.request", return_value=(reply, {})) as api, patch("image_provider.run"):
        image_scene({"visual_prompt": "Rain"}, {"style": "c"}, tmp_path, 1, ("gpt-image-1", "k"))
        assert api.call_args.args[3]["quality"] == "medium"
        monkeypatch.setenv("IMAGE_QUALITY", "ultra")
        with pytest.raises(ValueError, match="IMAGE_QUALITY"):
            image_scene({"visual_prompt": "Snow"}, {"style": "c"}, tmp_path, 1, ("gpt-image-1", "k"))
    api.assert_called_once()


def test_overlong_narration_is_refused_before_any_request(tmp_path):
    scene = {"dialogue": "এটি একটি অনেক লম্বা সংলাপ যা ছয় সেকেন্ডের দৃশ্যে কখনোই বলা যাবে না, তবুও লেখক আরও অনেক কথা যোগ করেছেন।" * 2}
    with patch("speech.urlopen") as call:
        with pytest.raises(ValueError, match="nothing was charged"):
            narration(scene, ("openai", "m", "v", "k"), tmp_path, 6)
    call.assert_not_called()


def inputs(*prompts):
    return {"resolution": "720p", "style": "c", "audio": False, "seconds_per_scene": 6,
            "scenes": [{"visual_prompt": p, "dialogue": ""} for p in prompts]}


def test_editing_one_scene_keeps_the_other_scenes_clips(tmp_path):
    first = scene_asset_folders(tmp_path, inputs("rain", "boat", "sun"))
    for number, folder in enumerate(first, 1):
        (folder / f"scene-{number:02}.mp4").write_bytes(b"paid clip")
    second = scene_asset_folders(tmp_path, inputs("rain", "a different boat", "sun"))
    assert second[0] == first[0] and second[2] == first[2] and second[1] != first[1]
    assert not (second[1] / "scene-02.mp4").exists()            # only the edited scene is generated again


def test_moved_scene_reuses_its_clip_and_legacy_runs_keep_their_folder(tmp_path):
    first = scene_asset_folders(tmp_path, inputs("rain", "boat"))
    (first[1] / "scene-02.mp4").write_bytes(b"boat clip")
    moved = scene_asset_folders(tmp_path, inputs("boat", "rain"))
    assert (moved[0] / "scene-01.mp4").read_bytes() == b"boat clip"
    old = tmp_path / "legacy"
    legacy = old / "assets" / legacy_asset_key(inputs("x"))
    legacy.mkdir(parents=True)
    assert scene_asset_folders(old, inputs("x")) == [legacy]   # in-flight paid submissions resume there


def test_codex_options_are_validated(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.cinematic import codex_options
    assert codex_options() == []
    monkeypatch.setenv("CODEX_MODEL", "gpt-5-codex"); monkeypatch.setenv("CODEX_REASONING_EFFORT", "low")
    assert codex_options() == ["-m", "gpt-5-codex", "-c", 'model_reasoning_effort="low"']
    monkeypatch.setenv("CODEX_MODEL", "x; rm -rf /")
    with pytest.raises(ValueError):
        codex_options()
