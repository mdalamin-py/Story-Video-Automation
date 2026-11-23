"""Configurable story routing. Credentials are resolved from the environment."""
import json
import os
import random
import time
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers import ProviderHTTPError, cached_story, request, save_story, story_cache_path


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    visual_prompt: str = Field(min_length=1)
    dialogue: str
    caption: str


class Story(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    story: str = Field(min_length=1)
    scenes: list[Scene]


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    base_url: str
    model: str = Field(min_length=1)
    key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    enabled: bool = True
    priority: int = 100
    estimated_usd: float = Field(ge=0, allow_inf_nan=False)
    token_limit: int = Field(default=4096, ge=128, le=32768)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def validate_url(self):
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an HTTPS base URL without credentials, query, or fragment.")
        return self


class Routing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: Literal["priority", "lowest_cost", "manual"] = "priority"
    manual_provider: str | None = None
    fallback: bool = True
    max_estimated_usd: float = Field(ge=0, allow_inf_nan=False)
    providers: list[Provider] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_names(self):
        names = {provider.name for provider in self.providers}
        if len(names) != len(self.providers):
            raise ValueError("Provider names must be unique.")
        if self.policy == "manual" and self.manual_provider not in names:
            raise ValueError("manual_provider must name a configured provider.")
        return self

    def candidates(self):
        eligible = [provider for provider in self.providers if provider.enabled]
        if self.policy == "manual":
            return [provider for provider in eligible if provider.name == self.manual_provider]
        if self.policy == "lowest_cost":
            return sorted(eligible, key=lambda provider: (provider.estimated_usd, provider.priority))
        return sorted(eligible, key=lambda provider: provider.priority)


def parse_routing(raw: str) -> Routing:
    try:
        return Routing.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError(str(exc.errors(include_input=False, include_url=False))) from None


def generate_story(config: Routing, brief: dict, instructions: str) -> dict:
    remaining = config.max_estimated_usd
    cap = os.environ.get("STORY_BUDGET_USD")
    if cap:
        budget = float(cap)
        if not 0 <= budget < float("inf"):
            raise ValueError("STORY_BUDGET_USD must be finite and nonnegative.")
        remaining = min(remaining, budget)
    # Any provider's plan for the identical brief and instructions is reused before spending again.
    cache = story_cache_path("story-router", instructions, brief)
    if (plan := cached_story(cache)) is not None and len(plan.get("scenes", [])) == brief["scene_count"]:
        return plan
    failures = []
    for provider in config.candidates():
        key = os.environ.get(provider.key_env, "").strip()
        if not key:
            failures.append(f"{provider.name}: missing credential")
            if config.fallback:
                continue
            break
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(brief, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            provider.token_parameter: provider.token_limit,
        }
        if provider.temperature is not None:
            payload["temperature"] = provider.temperature
        if provider.reasoning_effort is not None:
            payload["reasoning_effort"] = provider.reasoning_effort
        for attempt in range(2):
            if provider.estimated_usd > remaining:
                failures.append(f"{provider.name}: estimated budget exceeded")
                break
            remaining = round(remaining - provider.estimated_usd, 12)
            started = time.monotonic()
            try:
                response, _ = request(provider.base_url.rstrip("/") + "/chat/completions", "POST", key, payload)
                content = response["choices"][0]["message"]["content"]
                story = Story.model_validate_json(content)
                if len(story.scenes) != brief["scene_count"]:
                    raise ValueError("Scene count mismatch")
            except ProviderHTTPError as exc:
                failures.append(f"{provider.name}: HTTP {exc.status}")
                if exc.status == 429 and attempt == 0:
                    delay = exc.retry_after
                    if delay is None or delay <= 15:
                        time.sleep(max(delay or 0, 1 + random.random()))
                        continue
                break
            except (KeyError, IndexError, TypeError, ValueError, URLError, TimeoutError) as exc:
                failures.append(f"{provider.name}: {type(exc).__name__}")
                break
            if failures:
                print("Provider routing: " + "; ".join(failures), flush=True)
            print(f"Story provider: {provider.name} ({time.monotonic() - started:.2f}s)", flush=True)
            plan = story.model_dump()
            save_story(cache, plan)
            return plan
        if not config.fallback:
            break
    raise RuntimeError("No eligible story provider completed the request. " + "; ".join(failures))
