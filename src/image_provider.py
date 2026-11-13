"""Generate cached scene illustrations through a GPT Image endpoint."""
import base64
import hashlib
import json
import os

from media import run
from providers import ProviderHTTPError, request, required, write_json


def image_settings():
    provider = os.environ.get("IMAGE_PROVIDER", "").strip()
    if not provider:
        return None
    if provider != "openai":
        raise ValueError("IMAGE_PROVIDER must be openai.")
    return required("IMAGE_MODEL"), required("OPENAI_API_KEY")


def image_scene(scene, brief, folder, number, config):
    model, token = config
    payload = {
        "model": model, "size": "1024x1536", "output_format": "png",
        "prompt": scene["visual_prompt"] + "\nVisual style: " + brief["style"],
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    image = folder / (fingerprint + ".png")
    journal = image.with_suffix(".json")
    if not image.exists():
        if journal.exists():
            raise RuntimeError(f"Scene {number}: reconcile the previous image request before retrying.")
        write_json(journal, {"status": "submission pending"})
        try:
            response, _ = request("https://api.openai.com/v1/images/generations", "POST", token, payload)
        except ProviderHTTPError as exc:
            if exc.status in {400, 401, 403, 429}:
                journal.unlink()
            raise
        data = base64.b64decode(response["data"][0]["b64_json"], validate=True)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Image provider returned invalid PNG data.")
        temporary = image.with_suffix(".part")
        temporary.write_bytes(data)
        temporary.replace(image)
        write_json(journal, {"status": "completed"})
    clip = folder / f"illustration-{number:02}.mp4"
    run("-loop", "1", "-framerate", "30", "-i", str(image), "-t", "1",
        "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(clip))
    return clip
