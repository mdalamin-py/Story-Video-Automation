"""Admin-managed routing with server-bound endpoints and environment key references."""
import sys
from pathlib import Path

import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from provider_router import Routing


def validate_story_routing(raw):
    routing = Routing.model_validate(raw)
    for provider in routing.providers:
        if not provider.key_env.startswith("STUDIO_LLM_KEY_"):
            raise ValueError("Use a STUDIO_LLM_KEY_ credential reference.")
        suffix = provider.key_env.removeprefix("STUDIO_LLM_KEY_")
        endpoint = os.environ.get("STUDIO_LLM_URL_" + suffix, "").rstrip("/")
        if not endpoint or provider.base_url.rstrip("/") != endpoint:
            raise ValueError("The provider URL must match its server-configured endpoint.")
    return routing.model_dump()
