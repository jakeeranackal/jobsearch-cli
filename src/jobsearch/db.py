"""SQLite schema and access helpers.

One table for jobs (the universe of postings we've discovered), one for
applications (rows tracking what you've actually done with each job), and a
contacts table for recruiters/referrals tied to specific jobs.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


def _now() -> datetime:
    return datetime.now(timezone.utc)

DEFAULT_DB = Path("jobsearch.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,        -- source:source_id, e.g. greenhouse:airbnb:12345
    source          TEXT NOT NULL,           -- greenhouse | lever | ashby | rss
    source_company  TEXT NOT NULL,           -- slug, or RSS feed name
    title           TEXT NOT NULL,
    location        TEXT,
    department      TEXT,
    description     TEXT NOT NULL,
    url             TEXT NOT NULL,
    posted_at       TEXT,                    -- ISO date if known
    discovered_at   TEXT NOT NULL,           -- ISO datetime, when we first saw it
    is_open         INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_jobs_open ON jobs(is_open);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);

CREATE TABLE IF NOT EXISTS scores (
    job_id          TEXT NOT NULL,
    track           TEXT NOT NULL,           -- which resume track was scored
    score           REAL NOT NULL,           -- 0..1, higher is better
    scored_at       TEXT NOT NULL,
    PRIMARY KEY (job_id, track),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS applications (
    job_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL,           -- drafted|applied|interviewing|rejected|offer|withdrawn
    resume_track    TEXT,
    cover_letter_path TEXT,
    applied_at      TEXT,
    last_update_at  TEXT NOT NULL,
    next_followup_at TEXT,
    notes           TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL,
    name            TEXT NOT NULL,
    role            TEXT,                    -- recruiter | hiring_manager | referral | etc
    email           TEXT,
    linkedin        TEXT,
    notes           TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS status_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL,
    status          TEXT NOT NULL,
    at              TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS emails (
    message_id      TEXT PRIMARY KEY,        -- Gmail message id
    job_id          TEXT,
    sender          TEXT,
    subject         TEXT,
    received_at     TEXT,
    classification  TEXT,                    -- rejection | interview | offer | ack | other
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS connections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    company         TEXT,
    position        TEXT,
    email           TEXT,
    url             TEXT,
    connected_on    TEXT
);

CREATE INDEX IF NOT EXISTS idx_connections_company ON connections(company);

CREATE TABLE IF NOT EXISTS interviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT NOT NULL,
    starts_at       TEXT NOT NULL,           -- ISO datetime, local time
    duration_min    INTEGER NOT NULL DEFAULT 45,
    interviewer     TEXT,
    interviewer_email TEXT,
    calendar_event_id TEXT,
    thanks_drafted  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
"""

# Columns added after v0.1. connect() adds any that are missing so old
# databases keep working without a manual migration.
MIGRATIONS = {
    "jobs": {
        "company_name": "TEXT",
        "salary_min": "INTEGER",
        "salary_max": "INTEGER",
        "flags": "TEXT",
        "dup_of": "TEXT",
        "notified_at": "TEXT",
    },
    "applications": {
        "resume_path": "TEXT",
        "bundle_dir": "TEXT",
        "contact_email": "TEXT",
    },
}


@contextmanager
def connect(db_path: Path = DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with foreign keys on and Row factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def init_db(db_path: Path = DEFAULT_DB) -> None:
    """Create tables if they don't already exist."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_job(conn: sqlite3.Connection, job: dict) -> bool:
    """Insert a job if new, or refresh discovery timestamp if seen.

    Returns True if this was a new job.
    """
    row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    if row:
        conn.execute(
            "UPDATE jobs SET is_open = 1, salary_min = COALESCE(salary_min, ?), "
            "salary_max = COALESCE(salary_max, ?) WHERE id = ?",
            (job.get("salary_min"), job.get("salary_max"), job["id"]),
        )
        return False
    conn.execute(
        """
        INSERT INTO jobs (id, source, source_company, title, location, department,
                          description, url, posted_at, discovered_at, is_open,
                          company_name, salary_min, salary_max)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            job["id"],
            job["source"],
            job["source_company"],
            job["title"],
            job.get("location"),
            job.get("department"),
            job["description"],
            job["url"],
            job.get("posted_at"),
            _now().isoformat(timespec="seconds"),
            job.get("company_name"),
            job.get("salary_min"),
            job.get("salary_max"),
        ),
    )
    return True


def mark_jobs_closed(conn: sqlite3.Connection, source: str, source_company: str,
                     seen_ids: set[str]) -> int:
    """Mark jobs from a given source+company as closed if they weren't in the latest pull.

    Returns the number of jobs marked closed.
    """
    cur = conn.execute(
        """
        UPDATE jobs SET is_open = 0
        WHERE source = ? AND source_company = ? AND is_open = 1
              AND id NOT IN ({})
        """.format(",".join("?" * len(seen_ids)) or "''"),
        (source, source_company, *seen_ids) if seen_ids else (source, source_company),
    )
    return cur.rowcount


def record_score(conn: sqlite3.Connection, job_id: str, track: str, score: float) -> None:
    conn.execute(
        """
        INSERT INTO scores (job_id, track, score, scored_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_id, track) DO UPDATE SET
            score = excluded.score,
            scored_at = excluded.scored_at
        """,
        (job_id, track, score, _now().isoformat(timespec="seconds")),
    )


def update_application(conn: sqlite3.Connection, job_id: str, status: str,
                       followup_days: dict[str, int],
                       resume_track: str | None = None,
                       cover_letter_path: str | None = None,
                       notes: str | None = None,
                       resume_path: str | None = None,
                       bundle_dir: str | None = None) -> None:
    """Insert or update an application row, computing next_followup_at from status."""
    now = _now()
    _record_status(conn, job_id, status, now)
    next_followup = None
    days = followup_days.get(status)
    if days:
        next_followup = (now + timedelta(days=days)).isoformat(timespec="seconds")

    applied_at = now.isoformat(timespec="seconds") if status == "applied" else None

    existing = conn.execute(
        "SELECT applied_at, resume_track, cover_letter_path FROM applications WHERE job_id = ?",
        (job_id,),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE applications SET
                status = ?,
                resume_track = COALESCE(?, resume_track),
                cover_letter_path = COALESCE(?, cover_letter_path),
                applied_at = COALESCE(?, applied_at),
                last_update_at = ?,
                next_followup_at = ?,
                notes = COALESCE(?, notes),
                resume_path = COALESCE(?, resume_path),
                bundle_dir = COALESCE(?, bundle_dir)
            WHERE job_id = ?
            """,
            (status, resume_track, cover_letter_path, applied_at,
             now.isoformat(timespec="seconds"), next_followup, notes,
             resume_path, bundle_dir, job_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO applications (job_id, status, resume_track, cover_letter_path,
                                       applied_at, last_update_at, next_followup_at, notes,
                                       resume_path, bundle_dir)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, status, resume_track, cover_letter_path, applied_at,
             now.isoformat(timespec="seconds"), next_followup, notes,
             resume_path, bundle_dir),
        )


def _record_status(conn: sqlite3.Connection, job_id: str, status: str,
                   now: datetime) -> None:
    last = conn.execute(
        "SELECT status FROM status_history WHERE job_id = ? ORDER BY id DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if last and last["status"] == status:
        return
    conn.execute(
        "INSERT INTO status_history (job_id, status, at) VALUES (?, ?, ?)",
        (job_id, status, now.isoformat(timespec="seconds")),
    )


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def best_track(conn: sqlite3.Connection, job_id: str) -> tuple[str, float] | None:
    row = conn.execute(
        "SELECT track, score FROM scores WHERE job_id = ? ORDER BY score DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    return (row["track"], row["score"]) if row else None


def get_application(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None
