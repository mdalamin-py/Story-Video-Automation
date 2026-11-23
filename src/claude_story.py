"""Story plans from Claude through the official Anthropic SDK.

Credentials: ANTHROPIC_API_KEY, or any credential the SDK resolves on its own (for example an
`ant auth login` profile). CLAUDE_STORY_MODEL picks the model (default claude-opus-5-5) and
CLAUDE_STORY_EFFORT the effort (default medium, this model's own default).
"""
import os

from pydantic import BaseModel

DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class SceneOutput(BaseModel):
    visual_prompt: str
    dialogue: str
    caption: str


class StoryOutput(BaseModel):
    title: str
    description: str
    story: str
    scenes: list[SceneOutput]


def settings():
    model = os.environ.get("CLAUDE_STORY_MODEL", "").strip() or DEFAULT_MODEL
    effort = os.environ.get("CLAUDE_STORY_EFFORT", "").strip().lower() or "medium"
    if effort not in EFFORTS:
        raise ValueError("CLAUDE_STORY_EFFORT must be low, medium, high, xhigh or max.")
    return model, effort


def claude_story(brief, instructions, client=None):
    import anthropic

    model, effort = settings()
    client = client or anthropic.Anthropic()
    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=16000,
            system=instructions,
            messages=[{"role": "user", "content": _brief_text(brief)}],
            output_format=StoryOutput,
            output_config={"effort": effort},
            # If a safety classifier declines, the API re-runs the request on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("Claude rejected the API key. Check ANTHROPIC_API_KEY.") from None
    except anthropic.RateLimitError:
        raise RuntimeError("Claude is rate limited right now. Try again shortly.") from None
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude returned HTTP {exc.status_code}.") from None
    except anthropic.APIConnectionError:
        raise RuntimeError("Could not reach the Claude API. Check the internet connection.") from None
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write this story.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise RuntimeError("Claude's story plan was cut off before it was complete.")
    return response.parsed_output.model_dump()


def _brief_text(brief):
    import json
    return json.dumps(brief, ensure_ascii=False)
