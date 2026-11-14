import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from media import VERTICAL_SIZES, ffmpeg, render
from providers import STORY_INSTRUCTIONS, publish_facebook, publish_youtube, required, story_plan, write_json

from image_provider import image_scene, image_settings
from speech import routed_narration, settings as speech_settings
from video_providers import video_route

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"

PUBLISH_CREDENTIALS = {
    "youtube": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"),
    "facebook": ("FACEBOOK_GRAPH_VERSION", "FACEBOOK_PAGE_TOKEN", "FACEBOOK_PAGE_ID"),
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def demo_plan(brief):
    return {"title": "কাগজের নৌকা", "description": "একটি বৃষ্টিভেজা বিকেলের গল্প।",
            "story": brief["story"], "scenes": [
                {"visual_prompt": "Paper boat in rain", "dialogue": "", "caption": caption}
                for caption in ("বৃষ্টির বিকেল", "মীরার কাগজের নৌকা", "নৌকা ভেসে চলল")
            ]}


def validate(brief, plan=None):
    for field in ("story", "style", "language"):
        if not isinstance(brief[field], str) or not brief[field].strip():
            raise ValueError(f"Enter text in {field}.")
    for field, lower, upper in (("scene_count", 1, 5), ("seconds_per_scene", 4, 12)):
        if type(brief[field]) is not int or not lower <= brief[field] <= upper:
            raise ValueError(f"{field} must be an integer between {lower} and {upper}.")
    if brief["resolution"] not in {"720p", "1080p"}:
        raise ValueError("Muse source resolution must be 720p or 1080p.")
    if brief.get("export_resolution", brief["resolution"]) not in VERTICAL_SIZES:
        raise ValueError("export_resolution must be one of: " + ", ".join(VERTICAL_SIZES))
    for field in ("audio", "burn_captions", "made_for_kids", "synthetic_disclosure"):
        if type(brief[field]) is not bool:
            raise ValueError(f"{field} must be true or false.")
    if plan is None:
        return
    for field in ("title", "description", "story"):
        if not isinstance(plan[field], str) or not plan[field].strip():
            raise ValueError(f"The plan needs a {field}.")
    if len(plan["scenes"]) != brief["scene_count"]:
        raise ValueError("The plan's scene count must match the brief.")
    for scene in plan["scenes"]:
        for field in ("visual_prompt", "dialogue", "caption"):
            if not isinstance(scene[field], str):
                raise ValueError(f"Scene field {field} must be text.")
        if not scene["visual_prompt"].strip():
            raise ValueError("Each scene needs a visual prompt.")


def fingerprint(*paths):
    digest = hashlib.sha256()
    for path in paths:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\x00")
    return digest.hexdigest()


def render_fingerprint(brief_path, plan, video):
    scene_data = json.dumps(plan["scenes"], ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(fingerprint(brief_path, video).encode() + scene_data).hexdigest()


def draft(args):
    brief = load(args.brief)
    if args.demo:
        brief["scene_count"] = 3
    validate(brief)
    config = os.environ.get("STORY_PROVIDER_CONFIG", "").strip()
    snapshot = os.environ.get("STORY_PROVIDER_SNAPSHOT", "").strip()
    if args.demo:
        plan = demo_plan(brief)
    elif config or snapshot:
        from provider_router import generate_story, parse_routing

        routing = parse_routing(snapshot or (ROOT / config).read_text(encoding="utf-8-sig"))
        plan = generate_story(routing, brief, STORY_INSTRUCTIONS)
    else:
        if os.environ.get("STORY_BUDGET_USD"):
            raise ValueError("Configure STORY_PROVIDER_CONFIG to enforce a story budget.")
        plan = story_plan(brief)
    validate(brief, plan)
    folder = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True)
    write_json(folder / "brief.json", brief)
    write_json(folder / "plan.json", plan)
    write_json(folder / "job.json", {"demo": args.demo})
    print(f"Run: {folder.name}\nPlan: {folder / 'plan.json'}")
    return folder


def process(folder, args):
    brief_path, plan_path = folder / "brief.json", folder / "plan.json"
    brief, plan = load(brief_path), load(plan_path)
    validate(brief, plan)
    demo = load(folder / "job.json")["demo"]
    video = folder / "preview.mp4"
    render_state = folder / "render.json"
    if args.command == "render":
        if any(folder.glob("publish-*.json")):
            raise ValueError("This run has upload activity. Create a new draft for changes.")
        if args.video:
            if not args.video.is_file() or args.video.suffix.lower() != ".mp4":
                raise ValueError("--video must point to an existing MP4.")
            if args.video.resolve() != video.resolve():
                temporary = video.with_suffix(".part")
                shutil.copyfile(args.video, temporary)
                temporary.replace(video)
        else:
            ffmpeg()
            voice = None if demo else speech_settings()
            illustration = None if demo else image_settings()
            video_brief = {**brief, "audio": False} if voice else brief
            generation_inputs = {key: video_brief[key] for key in ("resolution", "style", "audio", "seconds_per_scene")}
            generation_inputs["scenes"] = [
                {key: scene[key] for key in ("visual_prompt", "dialogue")} for scene in plan["scenes"]
            ]
            video_provider = os.environ.get("VIDEO_PROVIDER") or os.environ.get("MUSE_PROVIDER", "")
            if illustration:
                generation_inputs["provider"] = "vertex-image" if len(illustration) == 3 else "openai-image"
                if len(illustration) == 3:
                    generation_inputs["image_endpoint"] = illustration[2]
                generation_inputs["image_model"] = illustration[0]

                def adapter(scene, video_brief, folder, number):
                    return image_scene(scene, video_brief, folder, number, illustration)
            elif not demo:
                adapter = video_route(video_provider, video_brief)
                if video_provider != "muse-video.com":
                    generation_inputs["provider"] = video_provider
                runway_model = os.environ.get("RUNWAY_VIDEO_MODEL", "").strip()
                if runway_model and runway_model != "gen4.5" and (
                    video_provider == "runway" or os.environ.get("VIDEO_FALLBACK_PROVIDER", "").strip() == "runway"
                ):
                    generation_inputs["runway_model"] = runway_model
            asset_key = hashlib.sha256(json.dumps(generation_inputs, sort_keys=True).encode()).hexdigest()
            assets = folder / "assets" / asset_key
            assets.mkdir(parents=True, exist_ok=True)
            if not demo and not illustration and video_provider == "muse-video.com":
                credits = brief["scene_count"] * brief["seconds_per_scene"] * (
                    75 if brief["resolution"] == "1080p" else 40)
                print(f"Estimated Muse credits: {credits}", flush=True)
            output = brief.get("export_resolution", brief["resolution"])
            if VERTICAL_SIZES[output][0] > VERTICAL_SIZES[brief["resolution"]][0]:
                print(f"Upscaling {brief['resolution']} source to {output}.", flush=True)
            voices = None
            if voice:
                voice_folder = folder / "narration" / asset_key
                voice_folder.mkdir(parents=True, exist_ok=True)
                voices = [routed_narration(scene, voice, voice_folder, brief["seconds_per_scene"], number)
                          for number, scene in enumerate(plan["scenes"], 1)]
            clips = [] if demo else [
                adapter(scene, video_brief, assets, number)
                for number, scene in enumerate(plan["scenes"], 1)
            ]
            render(clips, plan["scenes"], video_brief, folder, demo, voices)
        write_json(render_state, {"fingerprint": render_fingerprint(brief_path, plan, video)})
        print(f"Preview: {video}")
        return
    if args.command == "analytics":
        from engagement import engagement

        receipt = load(folder / f"publish-{args.platform}.json")
        print(json.dumps(engagement(args.platform, str(receipt["id"]))))
        return
    if demo:
        raise ValueError("Create a real draft to upload.")
    if not render_state.is_file() or not video.is_file():
        raise ValueError("Render the video before uploading.")
    if load(render_state)["fingerprint"] != render_fingerprint(brief_path, plan, video):
        raise ValueError("The scene plan, brief or video changed. Render again before uploading.")
    publishers = {"youtube": publish_youtube, "facebook": publish_facebook}
    platforms = list(publishers) if args.platform == "both" else [args.platform]
    for platform in platforms:
        state = folder / f"publish-{platform}.json"
        if state.exists():
            receipt = load(state)
            if "id" in receipt:
                print(f"{platform}: already submitted as {receipt['id']}")
                continue
            raise RuntimeError(f"Check {platform} for an existing upload before retrying.")
        for variable in PUBLISH_CREDENTIALS[platform]:
            required(variable)
        write_json(state, {"status": "submission pending", "public": args.public})
        receipt = publishers[platform](video, plan, brief, folder, args.public)
        write_json(state, {**receipt, "public": args.public})
        print(f"{platform}: {receipt.get('url', receipt['id'])}")


def check_setup(brief_path, platform):
    platforms = PUBLISH_CREDENTIALS if platform == "both" else (platform,)
    settings = [key for target in platforms for key in PUBLISH_CREDENTIALS[target]]
    story_config = os.environ.get("STORY_PROVIDER_CONFIG", "").strip()
    if story_config:
        from provider_router import Routing

        try:
            routing = Routing.model_validate_json((ROOT / story_config).read_text(encoding="utf-8-sig"))
        except ValueError:
            raise ValueError("Invalid story provider configuration. Review STORY_PROVIDER_CONFIG.") from None
        candidates = routing.candidates()
        if not routing.fallback:
            candidates = candidates[:1]
        if not any(os.environ.get(item.key_env, "").strip() for item in candidates):
            raise ValueError("Set a credential for an eligible story provider.")
    else:
        settings.extend(["OPENAI_API_KEY", "OPENAI_MODEL"])
        if os.environ.get("STORY_BUDGET_USD", "").strip():
            raise ValueError("Configure STORY_PROVIDER_CONFIG to enforce a story budget.")
    missing = [name for name in settings if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Missing settings in .env: " + ", ".join(missing))
    brief = load(brief_path)
    validate(brief)
    video_brief = {**brief, "audio": False} if speech_settings() else brief
    if not image_settings():
        video_route(os.environ.get("VIDEO_PROVIDER") or os.environ.get("MUSE_PROVIDER", ""), video_brief)
    subprocess.run([ffmpeg(), "-version"], check=True, stdout=subprocess.DEVNULL)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Story Video Automation")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("draft", "auto", "check"):
        step = commands.add_parser(name)
        step.add_argument("--brief", type=Path, default=ROOT / "input" / "brief.json")
    commands.choices["draft"].add_argument("--demo", action="store_true")
    for name in ("render", "upload", "analytics"):
        step = commands.add_parser(name)
        step.add_argument("run")
    commands.choices["analytics"].add_argument("--platform", choices=("youtube", "facebook"), required=True)
    commands.choices["render"].add_argument("--video", type=Path)
    for name in ("upload", "auto", "check"):
        step = commands.choices[name]
        step.add_argument("--platform", choices=("both", "youtube", "facebook"), default="both")
        if name != "check":
            step.add_argument("--public", action="store_true")
    args = parser.parse_args()
    load_env()
    if args.command == "draft":
        draft(args)
        return
    if args.command == "check":
        check_setup(args.brief, args.platform)
        print("Local configuration passed. No API calls made.")
        return
    if args.command == "auto":
        check_setup(args.brief, args.platform)
        args.demo = False
        folder = draft(args)
        process(folder, argparse.Namespace(command="render", video=None))
        args.command = "upload"
        process(folder, args)
        return
    if args.run in (".", "..") or Path(args.run).name != args.run:
        raise ValueError("Supply the run name printed by draft.")
    folder = RUNS / args.run
    if not (folder / "job.json").is_file():
        raise ValueError("Run not found.")
    lock = folder / "running.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise RuntimeError("Check for an active process before removing running.lock.") from None
    try:
        handle.close()
        process(folder, args)
    finally:
        lock.unlink()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Error: {exc}")
