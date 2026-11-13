import os
import shutil
import subprocess

VERTICAL_SIZES = {
    "720p": (720, 1280),
    "1080p": (1080, 1920),
    "1440p": (1440, 2560),
    "2160p": (2160, 3840),
}


def ffmpeg():
    path = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
    if path:
        return path
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except ImportError:
        raise ValueError("Set FFMPEG_PATH in .env to your ffmpeg.exe.") from None


def run(*args, folder=None):
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args],
                   cwd=folder, check=True)


def timestamp(seconds):
    return f"00:{seconds // 60:02}:{seconds % 60:02},000"


def render(clips, scenes, brief, folder, demo=False):
    width, height = VERTICAL_SIZES[brief.get("export_resolution", brief["resolution"])]
    source_width, source_height = VERTICAL_SIZES[brief["resolution"]]
    seconds = brief["seconds_per_scene"]
    captions = []
    for index, scene in enumerate(scenes):
        if scene["caption"].strip():
            captions.append(f"{len(captions) + 1}\n{timestamp(index * seconds)} --> "
                            f"{timestamp((index + 1) * seconds)}\n{scene['caption'].strip()}\n")
    (folder / "captions.srt").write_text("\n".join(captions), encoding="utf-8")
    if demo:
        colors = ("0x16304a", "0x3a2548", "0x125044", "0x4a3927", "0x2b3552")
        clips = []
        for index in range(len(scenes)):
            clip = folder / f"demo-{index:02}.mp4"
            run("-f", "lavfi", "-i", f"color={colors[index]}:s={source_width}x{source_height}:r=30",
                "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", str(clip))
            clips.append(clip)
    for index, clip in enumerate(clips):
        args = ["-i", str(clip), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(clip)],
                               capture_output=True, text=True)
        audio = "0:a:0" if brief["audio"] and "Audio:" in probe.stderr else "1:a:0"
        run(*args, "-map", "0:v:0", "-map", audio, "-af", "apad", "-t", str(seconds),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
                   f"tpad=stop_mode=clone:stop_duration={seconds}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", str(folder / f"cut-{index:02}.mp4"))
    (folder / "clips.txt").write_text("".join(
        f"file cut-{index:02}.mp4\n" for index in range(len(clips))), encoding="ascii")
    args = ["-c", "copy"]
    if captions and brief["burn_captions"]:
        args = ["-vf", "subtitles=captions.srt:force_style='FontName=Nirmala UI,FontSize=22,"
                "Outline=2,MarginV=26'", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "copy"]
    run("-f", "concat", "-safe", "1", "-i", "clips.txt", *args, "-movflags", "+faststart",
        "preview.tmp.mp4", folder=folder)
    (folder / "preview.tmp.mp4").replace(folder / "preview.mp4")
