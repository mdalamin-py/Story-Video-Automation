"""Local usage events with no credentials, prompt text, or URL paths."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def connect(path):
    db = sqlite3.connect(path, timeout=2)
    db.execute("""CREATE TABLE IF NOT EXISTS provider_requests (
        host TEXT NOT NULL, success INTEGER NOT NULL, latency_ms INTEGER NOT NULL,
        tokens INTEGER
    )""")
    return db


def record(host, success, latency_ms, result=None):
    path = os.environ.get("STUDIO_USAGE_DB")
    if not path:
        return
    usage = result.get("usage") if isinstance(result, dict) else None
    tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    tokens = tokens if type(tokens) is int and 0 <= tokens <= 2**53 else None
    try:
        with closing(connect(path)) as db, db:
            db.execute("INSERT INTO provider_requests VALUES(?,?,?,?)",
                       (host, int(success), latency_ms, tokens))
    except sqlite3.Error:
        # Telemetry must not change a paid request's reported outcome.
        return


def aggregate(path):
    if not Path(path).is_file():
        return []
    with closing(connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("""SELECT host, count(*) AS requests,
            sum(1-success) AS failures, CAST(avg(latency_ms) AS INTEGER) AS average_ms,
            sum(tokens) AS reported_tokens FROM provider_requests GROUP BY host ORDER BY host""")]
