"""Durable single-host queue for the production CLI."""
import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("STUDIO_DATA_DIR", ROOT / "runs" / "studio")).resolve()


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / "jobs.sqlite3", timeout=20, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, demo INTEGER NOT NULL, brief TEXT NOT NULL,
        state TEXT NOT NULL, run TEXT, error TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
        job_id TEXT NOT NULL, platform TEXT NOT NULL, public INTEGER NOT NULL,
        state TEXT NOT NULL, error TEXT, PRIMARY KEY(job_id, platform)
    )""")
    return db


def enqueue(brief, demo):
    job_id = uuid4().hex
    with closing(connect()) as db:
        db.execute("INSERT INTO jobs(id,demo,brief,state) VALUES(?,?,?,'PENDING')",
                   (job_id, int(demo), json.dumps(brief, ensure_ascii=False)))
    return job_id


def get_jobs():
    with closing(connect()) as db:
        return [dict(row) for row in db.execute(
            "SELECT id,demo,state,run,error,created FROM jobs ORDER BY rowid DESC LIMIT 100")]


def claim():
    with closing(connect()) as db:
        row = db.execute("""UPDATE jobs SET state='RUNNING'
            WHERE id=(SELECT id FROM jobs WHERE state='PENDING' ORDER BY rowid LIMIT 1)
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


def invoke(*arguments):
    result = subprocess.run([sys.executable, str(ROOT / "src" / "main.py"), *arguments],
                            cwd=ROOT, capture_output=True, encoding="utf-8",
                            errors="replace", timeout=7200)
    if result.returncode:
        # Provider errors and subprocess arguments can contain private data.
        raise RuntimeError("Production command failed: " + arguments[0])
    return result.stdout


def produce(row):
    brief_path = DATA / (row["id"] + ".json")
    try:
        brief_path.write_text(row["brief"], encoding="utf-8")
        arguments = ["draft", "--brief", str(brief_path)]
        if row["demo"]:
            arguments.append("--demo")
        output = invoke(*arguments)
        match = re.search(r"^Run: ([0-9-]+)$", output, flags=re.M)
        if not match:
            raise RuntimeError("Draft did not report a run name.")
        run = match[1]
        transition(row["id"], "RUNNING", "RENDERING", run)
        invoke("render", run)
        transition(row["id"], "RENDERING", "READY_TO_PUBLISH")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        if not transition(row["id"], "RENDERING", "FAILED", error=message):
            transition(row["id"], "RUNNING", "FAILED", error=message)
    finally:
        brief_path.unlink(missing_ok=True)


def schedule_delivery(job_id, platform, public):
    with closing(connect()) as db:
        result = db.execute("""INSERT OR IGNORE INTO deliveries
            SELECT id, ?, ?, 'PENDING', NULL FROM jobs
            WHERE id=? AND demo=0 AND state='READY_TO_PUBLISH'""",
            (platform, int(public), job_id))
        return result.rowcount == 1


def deliveries(job_id):
    with closing(connect()) as db:
        return [dict(row) for row in db.execute(
            "SELECT platform, public, state, error FROM deliveries WHERE job_id=?", (job_id,))]


def deliver_one():
    with closing(connect()) as db:
        task = db.execute("""UPDATE deliveries SET state='PUBLISHING' WHERE rowid=(
            SELECT rowid FROM deliveries WHERE state='PENDING' ORDER BY rowid LIMIT 1
        ) RETURNING *""").fetchone()
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
