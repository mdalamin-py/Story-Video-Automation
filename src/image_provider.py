"""Generate cached scene illustrations through a GPT Image endpoint."""
import base64
import hashlib
import json
import os
import re

from media import run
from providers import ProviderHTTPError, request, required, write_json


def image_settings():
    provider = os.environ.get("IMAGE_PROVIDER", "").strip()
    if not provider:
        return None
    model = required("IMAGE_MODEL")
    if provider == "openai":
        return model, required("OPENAI_API_KEY")
    if provider != "vertex":
        raise ValueError("IMAGE_PROVIDER must be openai or vertex.")
    project, region = required("VERTEX_PROJECT"), required("VERTEX_REGION")
    for value in (project, region, model):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", value):
            raise ValueError("Invalid Vertex project, region, or model identifier.")
    endpoint = (f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
                f"/locations/{region}/publishers/google/models/{model}:predict")
    from google_auth import access_token
    token = access_token()
    if not token:
        raise ValueError("Connect Google Vertex: press Sign in with Google on the Providers page, or set VERTEX_ACCESS_TOKEN in .env.")
    return model, token, endpoint


def image_scene(scene, brief, folder, number, config):
    model, token, *vertex = config
    payload = {
        "model": model, "size": "1024x1536", "output_format": "png",
        "prompt": scene["visual_prompt"] + "\nVisual style: " + brief["style"],
    }
    if not vertex and model.startswith("gpt-image"):
        # "auto" may pick high quality, which costs several times medium for a frame that is
        # later scaled and captioned; medium is the default, IMAGE_QUALITY overrides it.
        quality = os.environ.get("IMAGE_QUALITY", "").strip().lower() or "medium"
        if quality not in {"low", "medium", "high", "auto"}:
            raise ValueError("IMAGE_QUALITY must be low, medium, high or auto.")
        payload["quality"] = quality
    endpoint = vertex[0] if vertex else "https://api.openai.com/v1/images/generations"
    if vertex:
        payload = {"instances": [{"prompt": payload["prompt"]}],
                   "parameters": {"sampleCount": 1, "aspectRatio": "9:16"}}
    cache_payload = [endpoint, payload] if vertex else payload
    fingerprint = hashlib.sha256(json.dumps(cache_payload, sort_keys=True).encode()).hexdigest()
    image = folder / (fingerprint + ".png")
    journal = image.with_suffix(".json")
    if not image.exists():
        if journal.exists():
            raise RuntimeError(f"Scene {number}: reconcile the previous image request before retrying.")
        write_json(journal, {"status": "submission pending"})
        try:
            response, _ = request(endpoint, "POST", token, payload)
        except ProviderHTTPError as exc:
            if exc.status in {400, 401, 403, 429}:
                journal.unlink()
            raise
        encoded = (response["predictions"][0]["bytesBase64Encoded"] if vertex
                   else response["data"][0]["b64_json"])
        data = base64.b64decode(encoded, validate=True)
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
