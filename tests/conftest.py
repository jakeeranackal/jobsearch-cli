from pathlib import Path

import pytest

from jobsearch import company, db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def jd_text() -> str:
    return (FIXTURES / "jd_data_analyst.txt").read_text(encoding="utf-8")


@pytest.fixture
def resume_text() -> str:
    return (FIXTURES / "resume_data.txt").read_text(encoding="utf-8")


@pytest.fixture
def job(jd_text) -> dict:
    return {
        "id": "manual:acme-health:1",
        "source": "manual",
        "source_company": "acme-health",
        "company_name": "Acme Health",
        "title": "Data Analyst",
        "location": "Philadelphia, PA",
        "department": None,
        "description": jd_text,
        "url": "https://example.com/jobs/1",
        "posted_at": None,
    }


@pytest.fixture
def project(tmp_path, monkeypatch, resume_text):
    """A throwaway project folder with config, resume and DB; cwd set to it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "jobsearch.db")
    monkeypatch.setattr(company, "wikipedia_summary", lambda name, timeout=10.0: None)
    (tmp_path / "resumes").mkdir()
    (tmp_path / "resumes" / "data.txt").write_text(resume_text, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        "user: {name: Jordan Lee, email: jordan@example.com}\n"
        "resume_tracks:\n  data: {path: resumes/data.txt, keywords: [sql, tableau]}\n"
        "sources: {}\nfollowup_days: {applied: 7, interviewing: 5, drafted: 3}\n"
        "notify: {channel: none}\n",
        encoding="utf-8",
    )
    db.init_db(tmp_path / "jobsearch.db")
    return tmp_path
