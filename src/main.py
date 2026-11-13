import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from media import render, ffmpeg
from providers import muse_video, publish_facebook, publish_youtube, required, story_plan, write_json

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


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
        raise ValueError("resolution must be 720p or 1080p.")
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


def draft(args):
    brief = load(args.brief)
    if args.demo:
        brief["scene_count"] = 3
    validate(brief)
    plan = demo_plan(brief) if args.demo else story_plan(brief)
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
            assets = folder / "assets" / fingerprint(brief_path, plan_path)
            assets.mkdir(parents=True, exist_ok=True)
            if not demo:
                credits = brief["scene_count"] * brief["seconds_per_scene"] * (
                    75 if brief["resolution"] == "1080p" else 40)
                print(f"Estimated Muse credits: {credits}", flush=True)
            clips = [] if demo else [
                muse_video(scene, brief, assets, number)
                for number, scene in enumerate(plan["scenes"], 1)
            ]
            render(clips, plan["scenes"], brief, folder, demo)
        write_json(render_state, {"fingerprint": fingerprint(brief_path, plan_path, video)})
        print(f"Preview: {video}")
        return
    if demo:
        raise ValueError("Create a real draft to upload.")
    if not render_state.is_file() or not video.is_file():
        raise ValueError("Render the video before uploading.")
    if load(render_state)["fingerprint"] != fingerprint(brief_path, plan_path, video):
        raise ValueError("The plan or video changed. Render again before uploading.")
    publishers = {"youtube": publish_youtube, "facebook": publish_facebook}
    variables = {
        "youtube": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"),
        "facebook": ("FACEBOOK_GRAPH_VERSION", "FACEBOOK_PAGE_TOKEN", "FACEBOOK_PAGE_ID"),
    }
    platforms = list(publishers) if args.platform == "both" else [args.platform]
    for platform in platforms:
        state = folder / f"publish-{platform}.json"
        if state.exists():
            receipt = load(state)
            if "id" in receipt:
                print(f"{platform}: already submitted as {receipt['id']}")
                continue
            raise RuntimeError(f"Check {platform} for an existing upload before retrying.")
        for variable in variables[platform]:
            required(variable)
        write_json(state, {"status": "submission pending", "public": args.public})
        receipt = publishers[platform](video, plan, brief, folder, args.public)
        write_json(state, {**receipt, "public": args.public})
        print(f"{platform}: {receipt.get('url', receipt['id'])}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Story Video Automation")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("draft", "auto"):
        step = commands.add_parser(name)
        step.add_argument("--brief", type=Path, default=ROOT / "input" / "brief.json")
    commands.choices["draft"].add_argument("--demo", action="store_true")
    for name in ("render", "upload"):
        step = commands.add_parser(name)
        step.add_argument("run")
    commands.choices["render"].add_argument("--video", type=Path)
    for name in ("upload", "auto"):
        step = commands.choices[name]
        step.add_argument("--platform", choices=("both", "youtube", "facebook"), default="both")
        step.add_argument("--public", action="store_true")
    args = parser.parse_args()
    load_env()
    if args.command == "draft":
        draft(args)
        return
    if args.command == "auto":
        if required("MUSE_PROVIDER") != "muse-video.com":
            raise ValueError("Confirm that your Muse provider is muse-video.com.")
        required("MUSE_API_KEY")
        ffmpeg()
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
