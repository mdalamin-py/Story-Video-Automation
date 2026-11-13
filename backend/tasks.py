"""Redis-backed dispatch for the durable database queue."""
import os

from celery import Celery

from backend.jobs import claim, deliver_one, heartbeat, produce

app = Celery("studio", broker=os.environ["STUDIO_REDIS_URL"])
app.conf.update(
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "produce-pending-video": {"task": "studio.produce", "schedule": 10.0,
                                  "options": {"queue": "production", "expires": 10}},
        "submit-due-delivery": {"task": "studio.deliver", "schedule": 5.0,
                                "options": {"queue": "publishing", "expires": 5}},
    },
)


@app.task(name="studio.produce")
def produce_pending():
    heartbeat("production")
    row = claim()
    if row:
        produce(row)


@app.task(name="studio.deliver")
def submit_due():
    heartbeat("publishing")
    deliver_one()
