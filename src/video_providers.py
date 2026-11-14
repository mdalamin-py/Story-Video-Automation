import json
import os
import time
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

from providers import ProviderHTTPError, muse_video, request, required, write_json


def runway_video(scene, brief, folder, number, model="gen4.5"):
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
        payload = {
            "model": model, "promptText": prompt,
            "ratio": "1080:1920" if brief["resolution"] == "1080p" else "720:1280",
            "duration": brief["seconds_per_scene"],
        }
        if model != "gen4.5":
            payload["audio"] = brief["audio"]
        try:
            task, _ = request(base + "text_to_video", "POST", token, payload, headers)
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


RUNWAY_MODELS = {
    "gen4.5": ("720p", 2, 10, False),
    "kling3.0_standard": ("720p", 3, 15, True),
    "kling3.0_pro": ("1080p", 3, 15, True),
}


def select_video_provider(name, brief):
    if name not in VIDEO_ADAPTERS:
        raise ValueError("VIDEO_PROVIDER must be muse-video.com or runway.")
    if name == "muse-video.com":
        required("MUSE_API_KEY")
        return VIDEO_ADAPTERS[name]
    model = os.environ.get("RUNWAY_VIDEO_MODEL", "").strip() or "gen4.5"
    if model not in RUNWAY_MODELS:
        raise ValueError("Unsupported Runway model: choose Gen-4.5, Kling Standard, or Kling Pro.")
    resolution, shortest, longest, has_audio = RUNWAY_MODELS[model]
    if (brief["resolution"] != resolution or (brief["audio"] and not has_audio)
            or not shortest <= brief["seconds_per_scene"] <= longest):
        raise ValueError(f"{model} requires {resolution} source and {shortest}–{longest} second scenes."
                         + ("" if has_audio else " Disable source audio."))
    required("RUNWAY_API_KEY")

    def generate(scene, video_brief, folder, number):
        return VIDEO_ADAPTERS[name](scene, video_brief, folder, number, model=model)

    return generate



def video_route(primary_name, brief):
    primary = select_video_provider(primary_name, brief)
    backup_name = os.environ.get("VIDEO_FALLBACK_PROVIDER", "").strip()
    if backup_name == primary_name:
        raise ValueError("VIDEO_FALLBACK_PROVIDER must differ from VIDEO_PROVIDER.")
    backup = select_video_provider(backup_name, brief) if backup_name else None

    def render_scene(scene, video_brief, folder, number):
        journal = folder / f"scene-{number:02}.json"
        clip = folder / f"scene-{number:02}.mp4"
        backup_folder = folder / ("fallback-" + backup_name)
        route_record = folder / f"scene-{number:02}-route.json"
        if route_record.is_file():
            recorded = json.loads(route_record.read_text(encoding="utf-8"))["provider"]
            if recorded != backup_name:
                raise ValueError(f"Scene {number} already selected backup {recorded}. Restore that setting to resume.")
            return backup(scene, video_brief, backup_folder, number)
        try:
            return primary(scene, video_brief, folder, number)
        except ProviderHTTPError as exc:
            if backup is None or exc.status != 429 or journal.exists() or clip.exists():
                raise
            print(f"Scene {number}: {primary_name} rejected submission (429); using {backup_name}.", flush=True)
            backup_folder.mkdir(exist_ok=True)
            write_json(route_record, {"provider": backup_name})
            return backup(scene, video_brief, backup_folder, number)

    return render_scene
