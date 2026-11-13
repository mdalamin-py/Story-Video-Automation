import io
import json
import sys
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from speech import narration, speech_request


def test_speech_request_contracts():
    request = speech_request("openai", "tts-model", "voice", "key", "Hello")
    assert request.full_url.endswith("/audio/speech")
    assert json.loads(request.data)["response_format"] == "mp3"
    request = speech_request("elevenlabs", "tts-model", "voice", "key", "Hello")
    assert request.full_url.endswith("/text-to-speech/voice")
    assert json.loads(request.data)["model_id"] == "tts-model"


def test_normalization_cache_and_duration(tmp_path):
    source = io.BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 16000)
    scene = {"dialogue": "Hello"}
    config = ("openai", "model", "voice", "test")
    with patch("speech.urlopen", return_value=io.BytesIO(source.getvalue())) as call:
        first = narration(scene, config, tmp_path, 2)
        assert first.is_file()
        assert narration(scene, config, tmp_path, 2) == first
        with pytest.raises(ValueError, match="Shorten the dialogue"):
            narration(scene, config, tmp_path, 0.5)
        call.assert_called_once()
