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
