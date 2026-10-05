"""End-to-end pipeline test using synthetic in-memory data (no network)."""
from jobsearch import db


def test_pipeline_upsert_score_draft(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DEFAULT_DB", db_path)
    db.init_db(db_path)

    job = {
        "id": "greenhouse:test:1",
        "source": "greenhouse",
        "source_company": "test",
        "title": "Data Analyst",
        "location": "Philadelphia, PA",
        "department": "Analytics",
        "description": "Python pandas sql regression analytics",
        "url": "https://example.com/jobs/1",
        "posted_at": "2026-05-01",
    }

    with db.connect(db_path) as conn:
        assert db.upsert_job(conn, job) is True       # new
        assert db.upsert_job(conn, job) is False      # already seen
        db.record_score(conn, job["id"], "data", 0.42)
        db.update_application(
            conn, job["id"], "drafted",
            followup_days={"drafted": 3},
            resume_track="data",
        )

        rows = conn.execute(
            "SELECT score FROM scores WHERE job_id = ?", (job["id"],)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["score"] == 0.42

        app = conn.execute(
            "SELECT status, next_followup_at FROM applications WHERE job_id = ?",
            (job["id"],),
        ).fetchone()
        assert app["status"] == "drafted"
        assert app["next_followup_at"] is not None

