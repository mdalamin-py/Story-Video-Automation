import hashlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from backend import jobs
from backend.storage import archive_preview


def test_s3_archive_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_S3_BUCKET", "fixture")
    client = Mock()
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=Mock(return_value=client)))
    video = tmp_path / "preview.mp4"
    video.write_bytes(b"fixture")
    receipt = archive_preview(video, "demo-run")
    digest = hashlib.sha256(b"fixture").hexdigest()
    assert receipt["key"] == f"previews/demo-run/{digest}.mp4"
    client.upload_file.assert_called_once_with(str(video), "fixture", receipt["key"], ExtraArgs={
        "ContentType": "video/mp4", "Metadata": {"sha256": digest},
    })


def test_worker_reports_last_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    jobs.heartbeat("local")
    assert abs(jobs.worker_status()["local"]) < 2


def test_archive_url_is_scoped_and_short_lived(monkeypatch):
    import pytest
    from backend import storage

    monkeypatch.setenv("STUDIO_S3_BUCKET", "fixture")
    client = Mock()
    monkeypatch.setattr(storage, "s3_client", lambda: client)
    receipt = {"bucket": "fixture", "key": "previews/run/digest.mp4", "sha256": "digest"}
    storage.preview_url(receipt, "run")
    client.generate_presigned_url.assert_called_once_with(
        "get_object", Params={"Bucket": "fixture", "Key": receipt["key"]}, ExpiresIn=120,
    )
    with pytest.raises(ValueError, match="Unexpected archive key"):
        storage.preview_url(receipt, "other-run")


def test_metrics_requires_authentication(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api import app

    monkeypatch.setattr(jobs, "DATA", tmp_path)
    token = "a-test-token-at-least-24-characters"
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", token)
    jobs.enqueue({"story": "sample"}, True)
    jobs.heartbeat("local")
    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 401
        response = client.get("/metrics", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    assert 'studio_queue_items{queue="jobs",state="PENDING"} 1' in response.text
    assert 'studio_worker_last_seen_seconds{worker="local"}' in response.text


def test_provider_usage_retains_only_counts(tmp_path, monkeypatch):
    from src.usage import aggregate, record

    path = tmp_path / "usage.sqlite3"
    monkeypatch.setenv("STUDIO_USAGE_DB", str(path))
    record("provider.example", True, 100, {"usage": {"total_tokens": 17}, "message": "hidden"})
    record("provider.example", False, 200)
    assert aggregate(path) == [{
        "host": "provider.example", "requests": 2, "failures": 1,
        "average_ms": 150, "reported_tokens": 17,
    }]
    assert b"hidden" not in path.read_bytes()
