"""Per-scene narration with provider-specific requests and a local audio cache."""
import hashlib
import json
import os
import subprocess
import wave
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from media import ffmpeg
from providers import required


def settings():
    provider = os.environ.get("TTS_PROVIDER", "").strip()
    if not provider:
        return None
    if provider not in {"openai", "elevenlabs"}:
        raise ValueError("TTS_PROVIDER must be openai or elevenlabs.")
    primary = provider_settings(provider, "TTS")
    backup = os.environ.get("TTS_FALLBACK_PROVIDER", "").strip()
    if backup and (backup == provider or backup not in {"openai", "elevenlabs"}):
        raise ValueError("TTS fallback must be a different supported speech provider.")
    return primary, provider_settings(backup, "TTS_FALLBACK") if backup else None


def provider_settings(provider, prefix):
    key = required("OPENAI_API_KEY" if provider == "openai" else "ELEVENLABS_API_KEY")
    return provider, required(prefix + "_MODEL"), required(prefix + "_VOICE"), key


class SpeechRateLimited(RuntimeError):
    pass


LETTERS_PER_SECOND = 15.0   # about the pace make_beats.py assumes; works for Bangla and English letters


def estimated_seconds(text):
    return sum(ch.isalpha() for ch in text) / LETTERS_PER_SECOND + 0.35 * sum(text.count(p) for p in ",.!?।")


def routed_narration(scene, settings, folder, seconds, number):
    primary, backup = settings
    route = folder / f"scene-{number:02}-voice.json"
    if route.exists():
        selection = json.loads(route.read_text(encoding="utf-8"))
        if not backup or selection != list(backup[:3]):
            raise ValueError("Restore the recorded speech fallback settings to resume.")
        return narration(scene, backup, folder, seconds)
    try:
        return narration(scene, primary, folder, seconds)
    except SpeechRateLimited:
        if not backup:
            raise
        from providers import write_json

        print(f"Scene {number}: {primary[0]} rejected narration (429); using {backup[0]}.", flush=True)
        write_json(route, list(backup[:3]))
        return narration(scene, backup, folder, seconds)


def speech_request(provider, model, voice, key, text):
    if provider == "openai":
        endpoint = "https://api.openai.com/v1/audio/speech"
        headers = {"Authorization": "Bearer " + key}
        payload = {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
    else:
        endpoint = "https://api.elevenlabs.io/v1/text-to-speech/" + quote(voice, safe="")
        headers = {"xi-api-key": key}
        payload = {"model_id": model, "text": text}
    return Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(),
                   headers={**headers, "Content-Type": "application/json"})


def narration(scene, config, folder, seconds):
    text = scene["dialogue"].strip()
    if not text:
        return None
    provider, model, voice, key = config
    digest = hashlib.sha256(json.dumps([provider, model, voice, text]).encode()).hexdigest()
    audio = folder / (digest + ".wav")
    if not audio.is_file() and estimated_seconds(text) > seconds * 1.3:
        raise ValueError(f"Narration would take about {estimated_seconds(text):.1f}s for a {seconds}s scene. "
                         "Shorten the dialogue or extend the scene. (Checked before calling the speech service: nothing was charged.)")
    if not audio.is_file():
        raw = audio.with_suffix(".mp3.part")
        decoded = audio.with_suffix(".wav.part")
        try:
            try:
                with urlopen(speech_request(provider, model, voice, key, text), timeout=120) as reply:
                    with raw.open("wb") as out:
                        total = 0
                        while chunk := reply.read(65536):
                            total += len(chunk)
                            if total > 20 * 1024 * 1024:
                                raise ValueError("TTS response exceeded 20 MiB.")
                            out.write(chunk)
            except HTTPError as exc:
                if exc.code == 429:
                    raise SpeechRateLimited(f"{provider} rejected speech generation (429).") from None
                raise RuntimeError(f"{provider} speech request returned HTTP {exc.code}.") from None
            subprocess.run([ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", str(raw),
                            "-vn", "-af", "loudnorm=I=-16:TP=-2:LRA=7", "-ar", "48000",
                            "-ac", "2", "-c:a", "pcm_s16le", "-f", "wav", str(decoded)],
                           check=True)
            decoded.replace(audio)
        finally:
            raw.unlink(missing_ok=True)
            decoded.unlink(missing_ok=True)
    with wave.open(str(audio), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
    if duration <= 0 or duration > seconds:
        raise ValueError(f"Narration is {duration:.2f}s for a {seconds}s scene. Shorten the dialogue or extend the scene.")
    return audio
