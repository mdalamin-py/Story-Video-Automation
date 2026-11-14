import json
import os
import secrets
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.jobs import ROOT, deliveries, enqueue, get_jobs, invoke, lookup, recover_failed, schedule_delivery, summary, transition, worker_status

from backend.storage import preview_url
from backend.preferences import Preferences, get_preferences, save_preferences

app = FastAPI(title="Story Video Studio", docs_url=None, redoc_url=None)


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    story: str = Field(min_length=1, max_length=24000)
    final_changes: str = Field(default="", max_length=6000)
    language: str = Field(default="বাংলা", min_length=1, max_length=100)
    style: str = Field(default="Cinematic natural light", min_length=1, max_length=500)
    scene_count: int = Field(default=3, ge=1, le=5)
    seconds_per_scene: int = Field(default=6, ge=4, le=12)
    resolution: Literal["720p", "1080p"] = "1080p"
    export_resolution: Literal["720p", "1080p", "1440p", "2160p"] = "1080p"
    audio: bool = True
    burn_captions: bool = True
    made_for_kids: bool = False
    synthetic_disclosure: bool = False


class Submission(BaseModel):
    brief: Brief
    demo: bool = True


def authenticate(authorization: Annotated[str | None, Header()] = None):
    token = os.environ.get("STUDIO_ADMIN_TOKEN", "")
    if len(token) < 24:
        raise HTTPException(503, "Set STUDIO_ADMIN_TOKEN to at least 24 characters.")
    supplied = authorization or ""
    if not secrets.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
        raise HTTPException(401, "Invalid admin token.")


Admin = Annotated[None, Depends(authenticate)]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def dashboard():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/jobs")
def jobs(_: Admin):
    return get_jobs()


@app.post("/api/jobs", status_code=201)
def submit(submission: Submission, _: Admin):
    return {"id": enqueue(submission.brief.model_dump(), submission.demo)}


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str, _: Admin):
    if not transition(job_id, "PENDING", "CANCELLED"):
        raise HTTPException(409, "Only pending jobs can be cancelled.")
    return {"state": "CANCELLED"}


@app.get("/api/jobs/{job_id}/preview")
def preview(job_id: str, _: Admin):
    row = lookup(job_id)
    if not row or row["state"] != "READY_TO_PUBLISH":
        raise HTTPException(404, "Preview unavailable.")
    path = ROOT / "runs" / row["run"] / "preview.mp4"
    if path.is_file():
        return FileResponse(path, media_type="video/mp4")
    archive = path.with_name("archive.json")
    if not archive.is_file():
        raise HTTPException(404, "Preview file unavailable.")
    try:
        url = preview_url(json.loads(archive.read_text(encoding="utf-8")), row["run"])
    except Exception:
        raise HTTPException(502, "Archived preview unavailable.") from None
    return RedirectResponse(url, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


class Delivery(BaseModel):
    platform: Literal["youtube", "facebook"]
    public: bool = False
    publish_at: AwareDatetime | None = None


@app.post("/api/jobs/{job_id}/deliveries", status_code=202)
def publish(job_id: str, delivery: Delivery, _: Admin):
    if not schedule_delivery(job_id, delivery.platform, delivery.public, delivery.publish_at):
        raise HTTPException(409, "The real video must be ready and have no existing delivery for this platform.")
    return {"state": "PENDING"}


@app.get("/api/jobs/{job_id}/deliveries")
def delivery_status(job_id: str, _: Admin):
    return deliveries(job_id)


@app.get("/api/summary")
def activity_summary(_: Admin):
    return summary()


@app.get("/api/providers")
def provider_preferences(_: Admin):
    return get_preferences()


@app.put("/api/providers")
def update_provider_preferences(preferences: Preferences, _: Admin):
    if preferences.video_fallback and preferences.video_fallback == preferences.video_provider:
        raise HTTPException(422, "Choose a different video backup.")
    if preferences.story_routing is not None:
        from backend.story_settings import validate_story_routing

        try:
            preferences.story_routing = validate_story_routing(preferences.story_routing)
        except ValueError:
            raise HTTPException(422, "Invalid routing schema or server endpoint binding.") from None
    save_preferences(preferences)
    return preferences


@app.get("/api/jobs/{job_id}/analytics/{platform}")
def video_analytics(job_id: str, platform: Literal["youtube", "facebook"], _: Admin):
    row = lookup(job_id)
    if not row or not row["run"] or not (ROOT / "runs" / row["run"] / f"publish-{platform}.json").is_file():
        raise HTTPException(404, "No upload receipt is available.")
    try:
        return json.loads(invoke("analytics", row["run"], "--platform", platform))
    except (RuntimeError, ValueError):
        raise HTTPException(502, "Analytics unavailable. Check the platform permissions and video status.") from None


@app.get("/api/operations")
def operations(_: Admin):
    return {"worker_last_seen_seconds": worker_status(), **summary()}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(_: Admin):
    lines = [
        "# TYPE studio_queue_items gauge",
        "# TYPE studio_worker_last_seen_seconds gauge",
    ]
    for queue, states in summary().items():
        for state, count in states.items():
            labels = f'queue={json.dumps(queue)},state={json.dumps(state)}'
            lines.append(f"studio_queue_items{{{labels}}} {count}")
    for name, age in worker_status().items():
        lines.append(f"studio_worker_last_seen_seconds{{worker={json.dumps(name)}}} {age}")
    return "\n".join(lines) + "\n"


@app.post("/api/jobs/{job_id}/recover", status_code=202)
def recover(job_id: str, _: Admin):
    if not recover_failed(job_id):
        raise HTTPException(409, "Recovery requires a failed demo or a completed render. Check paid requests in the provider dashboard.")
    return {"state": "PENDING"}


@app.get("/api/provider-usage")
def provider_usage(_: Admin):
    from backend import jobs as job_store
    from src.usage import aggregate

    return aggregate(job_store.DATA / "usage.sqlite3", include_latest=True)


@app.get("/api/provider-health/openai")
def openai_health(_: Admin):
    from backend.provider_reports import connection_status

    return connection_status()


@app.get("/api/provider-costs/openai")
def provider_costs(_: Admin):
    from decimal import InvalidOperation
    from backend.provider_reports import openai_costs

    try:
        report = openai_costs()
    except (OSError, ValueError, InvalidOperation, TypeError, KeyError, AttributeError):
        raise HTTPException(502, "OpenAI cost report unavailable. Check the server admin credential.") from None
    if report is None:
        raise HTTPException(503, "Set OPENAI_ADMIN_KEY on the server to read OpenAI costs.")
    return report


@app.get("/api/provider-health/elevenlabs")
def elevenlabs_health(_: Admin):
    from backend.provider_reports import elevenlabs_subscription

    return elevenlabs_subscription()


@app.get("/api/provider-health/{provider}")
def media_health(provider: Literal["runway", "muse", "vertex"], _: Admin):
    from backend.provider_reports import media_account

    return media_account(provider)


@app.get("/api/provider-costs/runway")
def runway_credits(_: Admin):
    from backend.provider_reports import runway_usage

    try:
        report = runway_usage()
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(502, "Runway usage unavailable. Check the server credential.") from None
    if report is None:
        raise HTTPException(503, "Set RUNWAY_API_KEY on the server to read credit usage.")
    return report
