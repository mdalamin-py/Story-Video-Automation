"""Connect AI accounts from the dashboard: paste a key (tested before it is saved) or sign in with Google.

Keys are written to the local .env file and never sent back to the browser; the page only sees the
last four characters. Testing a key makes one free, read-only request to that service's own API."""
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.environment import ROOT, update_env_file

sys.path.insert(0, str(ROOT / "src"))

KEY = r"[A-Za-z0-9._\-:/+=]{8,400}"

SERVICES = {
    "gemini": {
        "label": "Gemini", "group": "Story", "use": "Story plans · cheapest", "google": "key",
        "get_key": "https://aistudio.google.com/apikey",
        "steps": ["Sign in with your Google account in Google AI Studio.", "Press Create API key and copy it.", "Paste it below."],
        "fields": [{"env": "GEMINI_API_KEY", "label": "Gemini API key", "secret": True, "pattern": KEY}],
    },
    "openai": {
        "label": "OpenAI", "group": "Story", "use": "Story plans, images and voice",
        "get_key": "https://platform.openai.com/api-keys",
        "steps": ["Sign in at platform.openai.com.", "Create a new secret key and copy it.", "Paste it below."],
        "note": "A ChatGPT Plus subscription does not include API use: the API is billed separately on platform.openai.com.",
        "fields": [{"env": "OPENAI_API_KEY", "label": "OpenAI API key", "secret": True, "pattern": KEY}],
    },
    "claude": {
        "label": "Claude", "group": "Story", "use": "Story plans · best writing",
        "get_key": "https://console.anthropic.com/settings/keys",
        "steps": ["Sign in at console.anthropic.com (the Claude Console).", "Press Create Key and copy it.", "Paste it below."],
        "note": "Your Claude.ai Pro or Max sign-in cannot be used by other apps. Apps use an API key from the Claude Console, "
                "which is billed per use, separately from a Claude.ai subscription.",
        "fields": [{"env": "ANTHROPIC_API_KEY", "label": "Claude API key", "secret": True, "pattern": KEY}],
    },
    "muse": {
        "label": "Muse Video", "group": "Video", "use": "Video clips",
        "get_key": "https://muse-video.com",
        "steps": ["Sign in at muse-video.com.", "Open your account's API section and copy your key.", "Paste it below."],
        "fields": [{"env": "MUSE_API_KEY", "label": "Muse API key", "secret": True, "pattern": KEY}],
    },
    "runway": {
        "label": "Runway", "group": "Video", "use": "Video clips · Gen-4.5 and Kling",
        "get_key": "https://dev.runwayml.com/",
        "steps": ["Sign in to the Runway developer portal.", "Create an API key and copy it.", "Paste it below."],
        "fields": [{"env": "RUNWAY_API_KEY", "label": "Runway API key", "secret": True, "pattern": KEY}],
    },
    "elevenlabs": {
        "label": "ElevenLabs", "group": "Voice", "use": "Narration · most natural",
        "get_key": "https://elevenlabs.io/app/settings/api-keys",
        "steps": ["Sign in at elevenlabs.io.", "Create an API key and copy it.", "Paste it below."],
        "fields": [{"env": "ELEVENLABS_API_KEY", "label": "ElevenLabs API key", "secret": True, "pattern": KEY}],
    },
    "vertex": {
        "label": "Google Vertex AI", "group": "Images", "use": "Imagen illustrations", "google": "signin",
        "get_key": "https://console.cloud.google.com/vertex-ai",
        "steps": ["Press Sign in with Google and choose your Google account in the browser.",
                  "Enter the Google Cloud project that has Vertex AI turned on.", "Save."],
        "note": "Google sign-in needs the free Google Cloud CLI on this PC. Without it, paste an access token instead "
                "(from gcloud auth print-access-token); those expire after an hour.",
        "fields": [{"env": "VERTEX_PROJECT", "label": "Google Cloud project ID", "secret": False, "pattern": r"[a-z][a-z0-9-]{4,61}[a-z0-9]"},
                   {"env": "VERTEX_REGION", "label": "Region", "secret": False, "pattern": r"[a-z]+-[a-z]+[0-9]{1,2}", "default": "us-central1"},
                   {"env": "VERTEX_ACCESS_TOKEN", "label": "Access token (only without Google sign-in)", "secret": True,
                    "pattern": r"[A-Za-z0-9._\-]{20,4096}", "optional": True}],
    },
}


def _value(name):
    return os.environ.get(name, "").strip()


def _masked(value):
    return "•••• " + value[-4:] if len(value) > 8 else "••••"


def status():
    from google_auth import gcloud, signed_in
    from ai_services import _codex_installed
    google_cli = bool(gcloud())
    google = google_cli and signed_in()
    rows = []
    for ident, service in SERVICES.items():
        fields = [{**{k: v for k, v in field.items() if k != "pattern"},
                   "value": "" if field["secret"] else _value(field["env"]),
                   "saved": _masked(_value(field["env"])) if field["secret"] and _value(field["env"]) else ""}
                  for field in service["fields"]]
        if ident == "vertex":
            connected = bool(_value("VERTEX_PROJECT")) and (bool(_value("VERTEX_ACCESS_TOKEN")) or google)
        else:
            connected = all(_value(field["env"]) for field in service["fields"] if not field.get("optional"))
        rows.append({"id": ident, **{k: service[k] for k in ("label", "group", "use", "get_key", "steps")},
                     "note": service.get("note", ""), "google": service.get("google", ""), "connected": connected,
                     "fields": fields, "testable": ident != "muse"})
    rows.append({"id": "codex", "label": "Codex", "group": "Story", "use": "Cinematic film scripts", "connected": _codex_installed(),
                 "fixed": "Signs in with your ChatGPT account inside the Codex app." })
    rows.append({"id": "edge", "label": "Microsoft Edge voices", "group": "Voice", "use": "Narration in 38 languages",
                 "connected": True, "fixed": "Free. Nothing to connect."})
    return {"services": rows, "google": {"cli": google_cli, "signed_in": google}}


def _read(url, headers):
    with urlopen(Request(url, headers=headers), timeout=12) as response:
        return json.load(response)


def test(ident, values):
    """One free, read-only request with the given values. Returns (ok, message)."""
    key = values.get(SERVICES[ident]["fields"][0]["env"], "")
    try:
        if ident == "gemini":
            _read("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", {"x-goog-api-key": key})
        elif ident == "openai":
            _read("https://api.openai.com/v1/models", {"Authorization": "Bearer " + key})
        elif ident == "claude":
            _read("https://api.anthropic.com/v1/models?limit=1", {"x-api-key": key, "anthropic-version": "2023-06-01"})
        elif ident == "runway":
            _read("https://api.dev.runwayml.com/v1/organization", {"Authorization": "Bearer " + key, "X-Runway-Version": "2024-11-06"})
        elif ident == "elevenlabs":
            _read("https://api.elevenlabs.io/v1/user/subscription", {"xi-api-key": key})
        elif ident == "vertex":
            from google_auth import _signed_in_token
            token = values.get("VERTEX_ACCESS_TOKEN") or _signed_in_token()
            if not token:
                return False, "Sign in with Google first, or paste an access token."
            project, region = values["VERTEX_PROJECT"], values.get("VERTEX_REGION") or "us-central1"
            _read(f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}/endpoints?pageSize=1",
                  {"Authorization": "Bearer " + token})
        else:
            return True, "Saved. Muse has no free check, so the key is tested by your first video."
    except HTTPError as error:
        if error.code in (401, 403):
            return False, f"{SERVICES[ident]['label']} refused it ({error.code}). Check that you copied the whole key" + (
                " and that Vertex AI is turned on for this project." if ident == "vertex" else ".")
        if error.code == 429:
            return True, "Key accepted (the service is busy right now)."
        return False, f"{SERVICES[ident]['label']} answered with error {error.code}."
    except (URLError, OSError, ValueError):
        return False, f"Could not reach {SERVICES[ident]['label']}. Check the internet connection."
    return True, "Connected."


def clean(ident, submitted):
    if ident not in SERVICES:
        raise KeyError(ident)
    values = {}
    for field in SERVICES[ident]["fields"]:
        value = str(submitted.get(field["env"], "")).strip()
        if not value and field["secret"] and _value(field["env"]):
            value = _value(field["env"])           # left blank: keep the saved key
        value = value or field.get("default", "")
        if not value:
            if field.get("optional"):
                continue
            raise ValueError(f"Enter the {field['label']}.")
        if not re.fullmatch(field["pattern"], value):
            raise ValueError(f"The {field['label']} does not look right. Copy it again without spaces.")
        values[field["env"]] = value
    return values


def connect(ident, submitted, check=True):
    values = clean(ident, submitted)
    ok, message = test(ident, values) if check else (True, "Saved without testing.")
    if not ok:
        return {"saved": False, "message": message}
    update_env_file(values)
    return {"saved": True, "message": message}


def disconnect(ident):
    if ident not in SERVICES:
        raise KeyError(ident)
    update_env_file({field["env"]: "" for field in SERVICES[ident]["fields"] if field["secret"]})
    return {"saved": True, "message": f"{SERVICES[ident]['label']} disconnected. The key was removed from .env."}
