from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from engagement import engagement


def test_youtube_normalizes_returned_statistics():
    result = {"items": [{"statistics": {"viewCount": "17", "commentCount": "2"}}]}
    with patch("engagement.youtube_access_token", return_value="fixture"):
        with patch("engagement.request", return_value=(result, {})) as request:
            assert engagement("youtube", "123456789ab") == {"views": 17, "comments": 2}
    assert "part=statistics" in request.call_args.args[0]


def test_facebook_preserves_zero_and_omits_unavailable_count(monkeypatch):
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "fixture")
    monkeypatch.setenv("FACEBOOK_GRAPH_VERSION", "v26.0")
    with patch("engagement.request", side_effect=[({"summary": {"total_count": 0}}, {}), ({}, {})]):
        assert engagement("facebook", "1234") == {"likes": 0}
