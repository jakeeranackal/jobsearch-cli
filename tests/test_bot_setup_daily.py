from datetime import datetime, timedelta

import yaml
from click.testing import CliRunner

from jobsearch import automation, db, notify, pipeline
from jobsearch.bot import Bot
from jobsearch.cli import cli


def test_bot_commands(project, job, monkeypatch):
    sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(notify, "telegram_send", lambda cfg, text, chat_id=None: sent.append((chat_id, text)))
    cfg = yaml.safe_load((project / "config.yaml").read_text())
    with db.connect() as conn:
        db.upsert_job(conn, job)
        db.record_score(conn, job["id"], "data", 0.5)

    Bot(cfg).handle("42", "/start")
    assert "chat id is 42" in sent[-1][1]

    cfg["telegram"] = {"chat_id": "42"}
    bot = Bot(cfg)
    bot.handle("99", "/today")                # strangers are ignored
    assert len(sent) == 1
    bot.handle("42", "/today")
    assert "Data Analyst" in sent[-1][1]
    bot.handle("42", f"/analyze {job['id']}")
    assert "Coverage" in sent[-1][1]
    bot.handle("42", f"/status {job['id']} nonsense")
    assert "Status must be" in sent[-1][1]
    bot.handle("42", f"/status {job['id']} applied")
    with db.connect() as conn:
        assert db.get_application(conn, job["id"])["status"] == "applied"


def test_daily_digest_reminds_about_thank_yous(project, job):
    cfg = yaml.safe_load((project / "config.yaml").read_text())
    with db.connect() as conn:
        db.upsert_job(conn, job)
        start = (datetime.now() - timedelta(hours=3)).isoformat(timespec="minutes")
        conn.execute("INSERT INTO interviews (job_id, starts_at, duration_min, interviewer) "
                     "VALUES (?, ?, 45, 'Sam Park')", (job["id"], start))
    text = automation.run_daily(cfg, log=lambda m: None)
    assert "send a thank-you" in text and "Sam Park" in text


def test_runner_script_written(project):
    path = automation._runner(project, "--alerts")
    assert "daily --alerts" in path.read_text()


def test_setup_wizard_writes_config(project, resume_text):
    (project / "config.yaml").unlink()
    (project / "my_resume.txt").write_text(resume_text, encoding="utf-8")
    answers_in = "\n".join([
        "Jordan Lee", "jordan@example.com", "555", "Philadelphia, PA", "", "",   # about you
        "my_resume.txt", "data", "", "n", "n",                                  # resume
        "data analyst, bi analyst", "n", "", "remote, philadelphia", "70000", "8",  # search
        "https://boards.greenhouse.io/acmehealth",                              # companies
        "",                                                                     # done
        "none", "n",                                                            # notify, gmail
        "n",                                                                    # pull now
    ]) + "\n"
    import jobsearch.company as company
    company_probe = company.probe
    company.probe = lambda s, slug: 12
    try:
        result = CliRunner().invoke(cli, ["setup"], input=answers_in, catch_exceptions=False)
    finally:
        company.probe = company_probe
    assert result.exit_code == 0, result.output
    cfg = yaml.safe_load((project / "config.yaml").read_text())
    assert cfg["user"]["name"] == "Jordan Lee"
    assert cfg["resume_tracks"]["data"]["path"] == "resumes/my_resume.txt"
    assert "sql" in cfg["resume_tracks"]["data"]["keywords"]
    assert cfg["search"]["roles"] == ["data analyst", "bi analyst"]
    assert cfg["search"]["salary_floor"] == 70000
    assert cfg["sources"]["greenhouse"] == ["acmehealth"]
    assert pipeline.resume_for(cfg, "data")[0] == "data"
