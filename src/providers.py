import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in .env before running this step.")
    return value


class ProviderHTTPError(RuntimeError):
    def __init__(self, host, status, retry_after=None):
        super().__init__(f"{host} returned HTTP {status}.")
        self.status = status
        self.retry_after = retry_after


def request(url, method="GET", token=None, payload=None, headers=None, stream=None):
    headers = dict(headers or {})
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
        stream = json.dumps(payload, ensure_ascii=False).encode()
    try:
        with urlopen(Request(url, data=stream, headers=headers, method=method), timeout=180) as reply:
            return json.loads(reply.read() or b"{}"), reply.headers
    except HTTPError as exc:
        retry = exc.headers.get("Retry-After", "")
        raise ProviderHTTPError(urlsplit(url).hostname, exc.code, int(retry) if retry.isdigit() else None) from None


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


STORY_INSTRUCTIONS = (
    "Adapt the supplied story or develop the supplied idea into an original short video. "
    "Preserve plot, characters, and ending unless final_changes overrides them. "
    "Follow the requested language, style, dialogue, and captions. "
    "Return a JSON object with title, description, story, and scenes. "
    "Use exactly scene_count scenes, each with visual_prompt, dialogue, and caption strings. "
    "Time each scene for seconds_per_scene. Keep the title within 95 characters. "
    "Keep character appearance, wardrobe, camera, lighting, and color consistent. "
    "Keep dialogue brief and leave unwanted dialogue or captions empty."
)


def story_plan(brief):
    response, _ = request("https://api.openai.com/v1/responses", "POST",
        required("OPENAI_API_KEY"), {
            "model": required("OPENAI_MODEL"), "store": False,
            "instructions": STORY_INSTRUCTIONS,
            "input": json.dumps(brief, ensure_ascii=False),
            "text": {"format": {"type": "json_object"}},
        })
    if response.get("status") != "completed":
        raise RuntimeError("Story generation did not complete.")
    output = "".join(part["text"] for item in response["output"]
                     for part in item.get("content", []) if part["type"] == "output_text")
    if not output:
        raise RuntimeError("The story service returned no usable text.")
    return json.loads(output)


def muse_video(scene, brief, folder, number):
    base = "https://muse-video.com/api/v1/"
    token = required("MUSE_API_KEY")
    clip = folder / f"scene-{number:02}.mp4"
    state_path = folder / f"scene-{number:02}.json"
    if clip.exists():
        return clip
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not state.get("task_id"):
            raise RuntimeError(f"Scene {number}: verify the previous submission with Muse before retrying.")
    else:
        prompt = scene["visual_prompt"] + "\nVisual style: " + brief["style"]
        if scene["dialogue"] and brief["audio"]:
            prompt += "\nSpoken dialogue, exactly as written: " + scene["dialogue"]
        write_json(state_path, {"submission": "pending"})
        response, _ = request(base + "generate", "POST", token, {
            "model": "happyhorse-1.0-text-to-video", "prompt": prompt,
            "duration": brief["seconds_per_scene"], "aspect_ratio": "9:16",
            "resolution": brief["resolution"], "generate_audio": brief["audio"],
        })
        state = response["data"]
        write_json(state_path, state)
    for _ in range(240):
        if state["status"] == "SUCCESS":
            url = state["response"]["resultUrls"][0]
            if urlsplit(url).scheme != "https":
                raise ValueError("Muse returned a non-HTTPS video URL.")
            temporary = clip.with_suffix(".part")
            with urlopen(url, timeout=180) as response, temporary.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            temporary.replace(clip)
            return clip
        if state["status"] == "FAILED":
            raise RuntimeError(f"Muse rejected scene {number}. Check {state_path.name} for details.")
        time.sleep(5)
        response, _ = request(base + "status?" + urlencode({"task_id": state["task_id"]}), token=token)
        state = response["data"]
        write_json(state_path, state)
    raise TimeoutError("Muse is still processing. Run render again to continue polling.")


def publish_youtube(path, plan, brief, folder, public):
    credentials = {key: required("YOUTUBE_" + key.upper())
                   for key in ("client_id", "client_secret", "refresh_token")}
    token_result, _ = request("https://oauth2.googleapis.com/token", "POST", headers={
        "Content-Type": "application/x-www-form-urlencoded"
    }, stream=urlencode({**credentials, "grant_type": "refresh_token"}).encode())
    token = token_result["access_token"]
    size = path.stat().st_size
    url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
    _, headers = request(url, "POST", token, {
        "snippet": {"title": plan["title"][:100], "description": plan["description"][:5000]},
        "status": {"privacyStatus": "public" if public else "private",
                   "selfDeclaredMadeForKids": brief["made_for_kids"],
                   "containsSyntheticMedia": brief["synthetic_disclosure"]},
    }, {"X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
    session_url = headers["Location"]
    parsed = urlsplit(session_url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.googleapis.com", "upload.youtube.com"}:
        raise RuntimeError("Unexpected YouTube upload URL.")
    with path.open("rb") as stream:
        result, _ = request(session_url, "PUT", token, headers={
            "Content-Type": "video/mp4", "Content-Length": str(size)
        }, stream=stream)
    return {"id": result["id"], "url": "https://youtu.be/" + result["id"]}


def publish_facebook(path, plan, brief, folder, public):
    version = required("FACEBOOK_GRAPH_VERSION")
    if not version.startswith("v") or not version[1:].replace(".", "").isdigit():
        raise ValueError("FACEBOOK_GRAPH_VERSION must look like v25.0.")
    token = required("FACEBOOK_PAGE_TOKEN")
    page = required("FACEBOOK_PAGE_ID")
    if not page.isascii() or not page.isdigit():
        raise ValueError("FACEBOOK_PAGE_ID must be numeric.")
    endpoint = f"https://graph.facebook.com/{version}/{page}/video_reels"
    result, _ = request(endpoint + "?upload_phase=start", "POST", token)
    upload = urlsplit(result["upload_url"])
    if upload.scheme != "https" or upload.hostname != "rupload.facebook.com":
        raise RuntimeError("Unexpected Facebook upload URL.")
    size = str(path.stat().st_size)
    with path.open("rb") as stream:
        transfer, _ = request(upload.geturl(), "POST", headers={
            "Authorization": "OAuth " + token, "offset": "0", "file_size": size,
            "Content-Type": "application/octet-stream", "Content-Length": size,
        }, stream=stream)
    if not transfer.get("success"):
        raise RuntimeError("Facebook did not accept the video file.")
    finish, _ = request(endpoint + "?" + urlencode({
        "video_id": result["video_id"], "upload_phase": "finish",
        "video_state": "PUBLISHED" if public else "DRAFT",
        "title": plan["title"], "description": plan["description"],
    }), "POST", token)
    if not finish.get("success"):
        raise RuntimeError("Facebook did not accept the finish request.")
    return {"id": result["video_id"], "status": "submitted for processing"}
