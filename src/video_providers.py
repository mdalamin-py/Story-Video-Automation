import json
import time
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

from providers import ProviderHTTPError, muse_video, request, required, write_json


def runway_video(scene, brief, folder, number):
    clip = folder / f"scene-{number:02}.mp4"
    journal = folder / f"scene-{number:02}.json"
    if clip.is_file():
        return clip
    token = required("RUNWAY_API_KEY")
    headers = {"X-Runway-Version": "2024-11-06"}
    base = "https://api.dev.runwayml.com/v1/"
    if journal.exists():
        task = json.loads(journal.read_text(encoding="utf-8"))
    else:
        prompt = scene["visual_prompt"] + "\nVisual style: " + brief["style"]
        if len(prompt.encode("utf-16-le")) // 2 > 1000:
            raise ValueError("Runway Gen-4.5 requires at most 1,000 UTF-16 units per scene prompt.")
        write_json(journal, {"submission": "pending"})
        try:
            task, _ = request(base + "text_to_video", "POST", token, {
                "model": "gen4.5", "promptText": prompt, "ratio": "720:1280",
                "duration": brief["seconds_per_scene"],
            }, headers)
        except ProviderHTTPError as exc:
            if exc.status in (400, 401, 403, 429):
                journal.unlink()
            raise
        write_json(journal, task)
    if not isinstance(task.get("id"), str):
        raise RuntimeError(f"Scene {number}: reconcile the previous Runway submission before retrying.")
    status_url = base + "tasks/" + quote(task["id"], safe="")
    for _ in range(240):
        if task.get("status") == "SUCCEEDED":
            url = task["output"][0]
            if urlsplit(url).scheme != "https":
                raise ValueError("Runway returned a non-HTTPS output URL.")
            temporary = clip.with_suffix(".part")
            with urlopen(url, timeout=180) as response, temporary.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            temporary.replace(clip)
            return clip
        if task.get("status") in {"FAILED", "CANCELLED"}:
            raise RuntimeError(f"Runway scene {number} ended with status {task['status']}.")
        time.sleep(5)
        task, _ = request(status_url, token=token, headers=headers)
        write_json(journal, task)
    raise TimeoutError("Runway is still processing. Run render again to continue polling.")


VIDEO_ADAPTERS = {"muse-video.com": muse_video, "runway": runway_video}


def select_video_provider(name, brief):
    if name not in VIDEO_ADAPTERS:
        raise ValueError("VIDEO_PROVIDER must be muse-video.com or runway.")
    if name == "runway" and (brief["resolution"] != "720p" or brief["audio"]
                             or not 2 <= brief["seconds_per_scene"] <= 10):
        raise ValueError("Runway Gen-4.5 requires 720p source, audio=false and 2–10 second scenes.")
    required("RUNWAY_API_KEY" if name == "runway" else "MUSE_API_KEY")
    return VIDEO_ADAPTERS[name]
