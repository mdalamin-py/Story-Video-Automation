import base64
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from image_provider import image_scene


def test_scene_image_is_cached(tmp_path):
    scene = {"visual_prompt": "Rain on a window"}
    brief = {"style": "Cinematic"}
    image = b"\x89PNG\r\n\x1a\n" + b"fixture"
    response = {"data": [{"b64_json": base64.b64encode(image).decode()}]}
    with patch("image_provider.request", return_value=(response, {})) as api:
        with patch("image_provider.run") as render:
            for _ in range(2):
                image_scene(scene, brief, tmp_path, 1, ("model", "key"))
    api.assert_called_once()
    assert render.call_count == 2
    assert next(tmp_path.glob("*.png")).read_bytes() == image


def test_unknown_image_submission_is_not_repeated(tmp_path):
    scene = {"visual_prompt": "Rain on a window"}
    with patch("image_provider.request", side_effect=TimeoutError) as api:
        with pytest.raises(TimeoutError):
            image_scene(scene, {"style": "Cinematic"}, tmp_path, 1, ("model", "key"))
        with pytest.raises(RuntimeError, match="reconcile"):
            image_scene(scene, {"style": "Cinematic"}, tmp_path, 1, ("model", "key"))
    api.assert_called_once()


def test_vertex_image_prediction_contract(tmp_path):
    scene = {"visual_prompt": "Rain"}
    endpoint = "https://us-central1-aiplatform.googleapis.com/v1/projects/demo/locations/us-central1/publishers/google/models/imagen:predict"
    image = b"\x89PNG\r\n\x1a\n" + b"fixture"
    response = {"predictions": [{"bytesBase64Encoded": base64.b64encode(image).decode()}]}
    with patch("image_provider.request", return_value=(response, {})) as api:
        with patch("image_provider.run"):
            image_scene(scene, {"style": "Cinematic"}, tmp_path, 1, ("imagen", "key", endpoint))
    assert api.call_args.args[0] == endpoint
    assert api.call_args.args[3]["parameters"] == {"sampleCount": 1, "aspectRatio": "9:16"}
