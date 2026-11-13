from unittest.mock import patch

import pytest

from video_providers import runway_video, select_video_provider


def test_runway_rejects_unsupported_source():
    with pytest.raises(ValueError, match="720p"):
        select_video_provider("runway", {"resolution": "1080p", "audio": False})


def test_runway_resumes_without_resubmitting(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNWAY_API_KEY", "test")
    journal = tmp_path / "scene-01.json"
    journal.write_text('{"id":"job-1","status":"RUNNING"}', encoding="utf-8")
    with patch("video_providers.request", return_value=({"status": "FAILED"}, {})) as request:
        with patch("video_providers.time.sleep"):
            with pytest.raises(RuntimeError, match="FAILED"):
                runway_video({}, {}, tmp_path, 1)
    request.assert_called_once()
    assert request.call_args.args[0].endswith("/tasks/job-1")
