from unittest.mock import Mock, patch

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

@pytest.mark.parametrize("status,expected_calls", [(429, 1), (503, 0)])
def test_fallback_only_after_rejected_submission(tmp_path, monkeypatch, status, expected_calls):
    from providers import ProviderHTTPError
    from video_providers import video_route

    monkeypatch.setenv("VIDEO_FALLBACK_PROVIDER", "runway")
    primary_error = ProviderHTTPError("muse-video.com", status)
    with patch("video_providers.select_video_provider") as select:
        primary = Mock(side_effect=primary_error)
        backup = Mock()
        select.side_effect = [primary, backup]
        route = video_route("muse-video.com", {})
        if expected_calls:
            route({}, {}, tmp_path, 1)
            route({}, {}, tmp_path, 1)
            assert backup.call_count == 2
            primary.assert_called_once()
            assert (tmp_path / "scene-01-route.json").is_file()
        else:
            with pytest.raises(ProviderHTTPError):
                route({}, {}, tmp_path, 1)
            backup.assert_not_called()


def test_runway_pro_model_is_forwarded(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNWAY_API_KEY", "test")
    monkeypatch.setenv("RUNWAY_VIDEO_MODEL", "kling3.0_pro")
    brief = {"resolution": "1080p", "audio": True, "seconds_per_scene": 6}
    with patch.dict("video_providers.VIDEO_ADAPTERS", {"runway": Mock()}) as adapters:
        select_video_provider("runway", brief)({}, brief, tmp_path, 1)
        adapters["runway"].assert_called_once_with({}, brief, tmp_path, 1, model="kling3.0_pro")
