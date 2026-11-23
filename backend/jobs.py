"""Durable single-host queue for the production CLI."""
import json
import os
import re
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.database import database
from backend.preferences import read_preferences
from backend.storage import archive_preview

from backend.environment import ROOT, load_env

load_env()
DATA = Path(os.environ.get("STUDIO_DATA_DIR", ROOT / "runs" / "studio")).resolve()


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = database(DATA / "jobs.sqlite3")
    db.execute("BEGIN")
    if os.environ.get("STUDIO_DATABASE_URL"):
        db.execute("SELECT pg_advisory_xact_lock(78124061)")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, demo INTEGER NOT NULL, brief TEXT NOT NULL,
        state TEXT NOT NULL, run TEXT, error TEXT, created TEXT DEFAULT (CAST(CURRENT_TIMESTAMP AS TEXT))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
        job_id TEXT NOT NULL, platform TEXT NOT NULL, public INTEGER NOT NULL,
        state TEXT NOT NULL, error TEXT, PRIMARY KEY(job_id, platform)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS delivery_schedule (
        job_id TEXT NOT NULL, platform TEXT NOT NULL, publish_at TEXT NOT NULL,
        PRIMARY KEY(job_id, platform)
    )""")
    db.execute("CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS job_preferences (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS worker_heartbeat (name TEXT PRIMARY KEY, seen TEXT NOT NULL)")
    db.commit()
    return db


def enqueue(brief, demo):
    job_id = uuid4().hex
    with closing(connect()) as db:
        db.execute("BEGIN")
        preferences = read_preferences(db).environment()
        db.execute("INSERT INTO job_preferences VALUES(?,?)", (job_id, json.dumps(preferences)))
        db.execute("INSERT INTO jobs(id,demo,brief,state) VALUES(?,?,?,'PENDING')",
                   (job_id, int(demo), json.dumps(brief, ensure_ascii=False)))
        db.commit()
    return job_id


def get_jobs():
    with closing(connect()) as db:
        rows = [dict(row) for row in db.execute(
            "SELECT id,demo,state,run,error,created,brief FROM jobs ORDER BY created DESC, id DESC LIMIT 100")]
        for row in rows:
            row["title"] = json.loads(row.pop("brief")).get("story", "Untitled story")[:90]
        return rows


def claim():
    with closing(connect()) as db:
        row = db.execute("""UPDATE jobs SET state='RUNNING'
            WHERE state='PENDING' AND id=(SELECT id FROM jobs WHERE state='PENDING' ORDER BY created,id LIMIT 1)
            RETURNING *""").fetchone()
        return dict(row) if row else None


def transition(job_id, expected, state, run=None, error=None):
    with closing(connect()) as db:
        changed = db.execute("""UPDATE jobs SET state=?, run=COALESCE(?,run), error=?
            WHERE id=? AND state=?""", (state, run, error, job_id, expected)).rowcount
        return changed == 1


def lookup(job_id):
    with closing(connect()) as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def invoke(*arguments, overrides=None):
    result = subprocess.run([sys.executable, str(ROOT / "src" / "main.py"), *arguments],
                            cwd=ROOT, env={**os.environ, **(overrides or {}), "STUDIO_USAGE_DB": str(DATA / "usage.sqlite3")}, capture_output=True, encoding="utf-8",
                            errors="replace", timeout=7200)
    if result.returncode:
        # Provider errors and subprocess arguments can contain private data.
        raise RuntimeError("Production command failed: " + arguments[0])
    return result.stdout


def produce(row):
    brief_path = DATA / (row["id"] + ".json")
    try:
        if row["run"] and not row["demo"]:
            # Recovery of a finished render only retries its deterministic archive.
            run = row["run"]
            folder = ROOT / "runs" / run
            if not (folder / "render.json").is_file() or not (folder / "preview.mp4").is_file():
                raise RuntimeError("Completed render files are missing.")
            if not transition(row["id"], "RUNNING", "RENDERING"):
                return
            archive_job(run)
            transition(row["id"], "RENDERING", "READY_TO_PUBLISH")
            return
        brief_path.write_text(row["brief"], encoding="utf-8")
        arguments = ["draft", "--brief", str(brief_path)]
        if row["demo"]:
            arguments.append("--demo")
        with closing(connect()) as db:
            preferences = db.execute("SELECT value FROM job_preferences WHERE id=?", (row["id"],)).fetchone()
        overrides = json.loads(preferences["value"]) if preferences else {}
        output = invoke(*arguments, overrides=overrides)
        match = re.search(r"^Run: ([0-9-]+)$", output, flags=re.M)
        if not match:
            raise RuntimeError("Draft did not report a run name.")
        run = match[1]
        if not transition(row["id"], "RUNNING", "RENDERING", run):
            return
        invoke("render", run, overrides=overrides)
        if not row["demo"]:
            archive_job(run)
        transition(row["id"], "RENDERING", "READY_TO_PUBLISH")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        if not transition(row["id"], "RENDERING", "FAILED", error=message):
            transition(row["id"], "RUNNING", "FAILED", error=message)
    finally:
        brief_path.unlink(missing_ok=True)


def schedule_delivery(job_id, platform, public, publish_at=None):
    with closing(connect()) as db:
        db.execute("BEGIN")
        result = db.execute("""INSERT INTO deliveries (job_id, platform, public, state, error)
            SELECT id, ?, ?, 'PENDING', NULL FROM jobs
            WHERE id=? AND demo=0 AND state='READY_TO_PUBLISH'
            ON CONFLICT(job_id,platform) DO NOTHING""",
            (platform, int(public), job_id))
        created = result.rowcount == 1
        if created and publish_at:
            db.execute("INSERT INTO delivery_schedule VALUES(?,?,?)",
                       (job_id, platform, publish_at.astimezone(UTC).isoformat()))
        db.commit()
        return created


def deliveries(job_id):
    with closing(connect()) as db:
        return [dict(row) for row in db.execute(
            """SELECT d.platform, d.public, d.state, d.error, s.publish_at FROM deliveries d
            LEFT JOIN delivery_schedule s USING(job_id, platform) WHERE d.job_id=?""", (job_id,))]


def deliver_one():
    with closing(connect()) as db:
        task = db.execute("""UPDATE deliveries SET state='PUBLISHING' WHERE state='PENDING' AND (job_id,platform)=(
            SELECT d.job_id,d.platform FROM deliveries d LEFT JOIN delivery_schedule s USING(job_id, platform)
            WHERE d.state='PENDING' AND (s.publish_at IS NULL OR s.publish_at <= ?)
            ORDER BY COALESCE(s.publish_at, ''), d.job_id,d.platform LIMIT 1
        ) RETURNING *""", (datetime.now(UTC).isoformat(),)).fetchone()
        if task is None:
            return False
        row = lookup(task["job_id"])
        args = ["upload", row["run"], "--platform", task["platform"]]
        if task["public"]:
            args.append("--public")
        try:
            invoke(*args)
            state, error = "SUBMITTED", None
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            state, error = "FAILED", "Review platform and local receipt before retrying."
        db.execute("UPDATE deliveries SET state=?,error=? WHERE job_id=? AND platform=?",
                   (state, error, task["job_id"], task["platform"]))
        return True

def summary():
    with closing(connect()) as db:
        result = {}
        for table in ("jobs", "deliveries"):
            result[table] = {row["state"]: row["total"] for row in db.execute(
                f"SELECT state,count(*) AS total FROM {table} GROUP BY state").fetchall()}
        return result


def archive_job(run):
    folder = ROOT / "runs" / run
    try:
        receipt = archive_preview(folder / "preview.mp4", run)
    except Exception as exc:
        raise RuntimeError("Preview archive failed: " + type(exc).__name__) from None
    if receipt:
        temporary = folder / "archive.tmp"
        temporary.write_text(json.dumps(receipt), encoding="utf-8")
        temporary.replace(folder / "archive.json")


def heartbeat(name):
    with closing(connect()) as db:
        db.execute("""INSERT INTO worker_heartbeat(name,seen) VALUES(?,?)
            ON CONFLICT(name) DO UPDATE SET seen=excluded.seen""",
            (name, datetime.now(UTC).isoformat()))


def worker_status():
    now = datetime.now(UTC)
    with closing(connect()) as db:
        rows = db.execute("SELECT name,seen FROM worker_heartbeat").fetchall()
    return {row["name"]: round((now - datetime.fromisoformat(row["seen"])).total_seconds(), 1)
            for row in rows}


def recover_failed(job_id):
    row = lookup(job_id)
    if not row or row["state"] != "FAILED":
        return False
    if not row["demo"]:
        run = row["run"]
        if not run or not re.fullmatch(r"[0-9-]+", run):
            return False
        folder = ROOT / "runs" / run
        if not all((folder / name).is_file() for name in ("render.json", "preview.mp4")):
            return False
    return transition(job_id, "FAILED", "PENDING")
