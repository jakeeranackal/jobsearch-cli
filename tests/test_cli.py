import json
import threading
import urllib.error
import urllib.request

import pytest
from click.testing import CliRunner

from jobsearch import dashboard, db
from jobsearch.cli import cli


def _run(*args, input=None):
    result = CliRunner().invoke(cli, list(args), input=input, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def test_add_analyze_apply_check_export_flow(project, jd_text):
    (project / "listing.txt").write_text(jd_text, encoding="utf-8")
    out = _run("add", "--file", "listing.txt", "--title", "Data Analyst", "--company", "Acme Health")
    assert "Added" in out
    with db.connect() as conn:
        job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
        assert conn.execute("SELECT salary_min FROM jobs").fetchone()[0] == 75000

    out = _run("analyze", job_id)
    assert "BURIED" in out and "Tableau" in out

    _run("apply", job_id, "--no-open", "--applied")
    folder = next((project / "applications").iterdir())
    names = {p.name for p in folder.iterdir()}
    assert {"analysis.md", "cover_letter.md", "tailor_notes.md", "CLAUDE_BRIEF.md"} <= names
    brief = (folder / "CLAUDE_BRIEF.md").read_text(encoding="utf-8")
    assert "Never submit" in brief and f"jobsearch check {job_id}" in brief
    with db.connect() as conn:
        app = db.get_application(conn, job_id)
    assert app["status"] == "applied" and app["resume_path"]

    # Simulate Claude Code editing the resume, then check and export it
    md = next(folder.glob("*_Resume_*.md"))
    md.write_text(md.read_text(encoding="utf-8").replace(
        "Built Excel reports", "Built Tableau dashboards"), encoding="utf-8")
    out = _run("check", job_id)
    assert "Nothing invented" in out
    md.write_text(md.read_text(encoding="utf-8") + "- Led a Snowflake migration\n", encoding="utf-8")
    assert "Snowflake" in _run("check", job_id)
    _run("export", job_id)
    from jobsearch import resume_io
    assert "Tableau dashboards" in resume_io.read_text(md.with_suffix(".docx"))

    assert "Applications sent: 1" in _run("report")
    assert "Data Analyst" in _run("digest", "--all")


def test_dashboard_api(project, job):
    with db.connect() as conn:
        db.upsert_job(conn, job)
        db.record_score(conn, job["id"], "data", 0.5)
    srv = dashboard.serve(0, {"applied": 7})
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        board = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/board"))
        assert board["columns"]["matches"][0]["id"] == job["id"]
        body = json.dumps({"job_id": job["id"], "status": "applied"}).encode()
        plain = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", data=body,
                                       headers={"Content-Type": "text/plain"})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(plain)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", data=body,
                                     headers={"Content-Type": "application/json"})
        assert json.load(urllib.request.urlopen(req))["ok"]
        board = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/board"))
        assert board["columns"]["applied"][0]["id"] == job["id"]
    finally:
        srv.shutdown()


def test_no_ai_dependency_anywhere():
    import pathlib

    import jobsearch

    src = pathlib.Path(jobsearch.__file__).parent
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "anthropic" not in text.lower(), py
