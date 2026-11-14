import concurrent.futures

from fastapi.testclient import TestClient

from backend import jobs
from backend.api import app


def test_demo_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    token = "a-test-token-at-least-24-characters"
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", token)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert TestClient(app).get("/api/jobs").status_code == 401
    assert client.post("/api/jobs", json={"brief": {"story": ""}}).status_code == 422
    response = client.post("/api/jobs", json={"brief": {
        "story": "A paper boat", "seconds_per_scene": 4,
        "resolution": "720p", "export_resolution": "720p",
    }})
    assert response.status_code == 201
    job_id = response.json()["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: jobs.claim(), range(2)))
    assert sum(row is not None for row in claimed) == 1
    jobs.produce(next(row for row in claimed if row))
    assert jobs.lookup(job_id)["state"] == "READY_TO_PUBLISH"
    preview = client.get(f"/api/jobs/{job_id}/preview")
    assert preview.status_code == 200
    assert preview.content[4:8] == b"ftyp"
    assert client.post(f"/api/jobs/{job_id}/deliveries", json={"platform": "youtube"}).status_code == 409


def test_platform_deliveries_are_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    job_id = jobs.enqueue({"story": "fixture"}, False)
    assert jobs.transition(job_id, "PENDING", "READY_TO_PUBLISH", "20260101-123456-123456")
    assert jobs.schedule_delivery(job_id, "youtube", False)
    assert not jobs.schedule_delivery(job_id, "youtube", True)
    assert jobs.schedule_delivery(job_id, "facebook", False)

    def upload(*args):
        if args[-1] == "youtube":
            raise RuntimeError("simulated service outage")

    monkeypatch.setattr(jobs, "invoke", upload)
    assert jobs.deliver_one()
    assert jobs.deliver_one()
    assert not jobs.deliver_one()
    states = {row["platform"]: row["state"] for row in jobs.deliveries(job_id)}
    assert states == {"youtube": "FAILED", "facebook": "SUBMITTED"}


def test_scheduled_delivery_waits(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setattr(jobs, "DATA", tmp_path)
    job_id = jobs.enqueue({"story": "fixture"}, False)
    assert jobs.transition(job_id, "PENDING", "READY_TO_PUBLISH", "20260101-123456-123456")
    later = datetime.now(UTC) + timedelta(hours=1)
    assert jobs.schedule_delivery(job_id, "youtube", True, later)
    assert not jobs.deliver_one()
    assert jobs.deliveries(job_id)[0]["publish_at"] == later.isoformat()
    assert jobs.summary()["deliveries"] == {"PENDING": 1}


def test_queue_captures_provider_defaults(tmp_path, monkeypatch):
    import json
    from contextlib import closing
    from backend.preferences import Preferences, save_preferences

    monkeypatch.setattr(jobs, "DATA", tmp_path)
    save_preferences(Preferences(video_provider="runway", story_budget_usd=0.02))
    job = jobs.enqueue({"story": "fixture"}, False)
    save_preferences(Preferences(video_provider="muse-video.com"))
    with closing(jobs.connect()) as db:
        value = db.execute("SELECT value FROM job_preferences WHERE id=?", (job,)).fetchone()[0]
    assert json.loads(value) == {"VIDEO_PROVIDER": "runway", "STORY_BUDGET_USD": "0.02"}


def test_recovery_only_requeues_safe_work(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    monkeypatch.setattr(jobs, "ROOT", tmp_path)
    demo = jobs.enqueue({"story": "demo"}, True)
    paid = jobs.enqueue({"story": "paid"}, False)
    run = "20261114-000000-000001"
    assert jobs.transition(demo, "PENDING", "FAILED")
    assert jobs.transition(paid, "PENDING", "FAILED", run)
    assert jobs.recover_failed(demo)
    assert not jobs.recover_failed(demo)
    assert not jobs.recover_failed(paid)
    folder = tmp_path / "runs" / run
    folder.mkdir(parents=True)
    (folder / "render.json").write_text("{}")
    (folder / "preview.mp4").write_bytes(b"video")
    assert jobs.recover_failed(paid)
    assert jobs.transition(paid, "PENDING", "RUNNING")

    def forbidden(*args, **kwargs):
        raise AssertionError("Recovery must not invoke a paid CLI command.")

    monkeypatch.setattr(jobs, "invoke", forbidden)
    jobs.produce(jobs.lookup(paid))
    assert jobs.lookup(paid)["state"] == "READY_TO_PUBLISH"


def test_abandoned_job_reconciliation(tmp_path, monkeypatch):
    import pytest
    from backend.recovery import reconcile

    monkeypatch.setattr(jobs, "DATA", tmp_path)
    demo = jobs.enqueue({"story": "demo"}, True)
    paid = jobs.enqueue({"story": "paid"}, False)
    assert jobs.transition(demo, "PENDING", "RUNNING")
    assert jobs.transition(paid, "PENDING", "RUNNING")
    with pytest.raises(ValueError, match="Stop every worker"):
        reconcile(demo, False)
    assert jobs.lookup(demo)["state"] == "RUNNING"
    assert reconcile(demo, True)
    assert jobs.lookup(demo)["state"] == "PENDING"
    assert not reconcile(paid, True)
    assert jobs.lookup(paid)["state"] == "FAILED"


def test_admin_routing_cannot_retarget_server_key(monkeypatch):
    import pytest
    from backend.story_settings import validate_story_routing

    monkeypatch.setenv("STUDIO_LLM_URL_PRIMARY", "https://example.com/v1")
    provider = {"name": "main", "model": "demo", "key_env": "STUDIO_LLM_KEY_PRIMARY",
                "base_url": "https://example.com/v1", "estimated_usd": 0.01}
    routing = {"max_estimated_usd": 0.05, "providers": [provider]}
    assert validate_story_routing(routing)["providers"][0]["model"] == "demo"
    provider["base_url"] = "https://different.example/v1"
    with pytest.raises(ValueError, match="server-configured endpoint"):
        validate_story_routing(routing)
