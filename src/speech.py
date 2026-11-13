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
    key = required("OPENAI_API_KEY" if provider == "openai" else "ELEVENLABS_API_KEY")
    return provider, required("TTS_MODEL"), required("TTS_VOICE"), key


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
