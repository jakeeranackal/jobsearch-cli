"""End-to-end pipeline test using synthetic in-memory data (no network)."""
from datetime import datetime
from pathlib import Path

from jobsearch import db, drafter


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


def test_drafter_renders_with_required_fields(tmp_path):
    user = {
        "name": "Test User",
        "email": "t@example.com",
        "phone": "555",
        "location": "City",
        "linkedin": "",
        "github": "",
    }
    job = {
        "title": "Data Analyst",
        "source_company": "acme-corp",
        "location": "Remote",
        "url": "https://example.com/1",
    }
    body = drafter.render(
        user=user, job=job, resume_track="data", score=0.42,
        matched_keywords=["python", "sql"],
        resume_highlights=["Built X", "Shipped Y"],
    )
    assert "Data Analyst" in body
    assert "Acme Corp" in body
    assert "Test User" in body
    assert "python, sql" in body

    out = drafter.save(tmp_path, "greenhouse:test:1", body)
    assert out.exists()
    assert out.read_text().startswith("Test User")
