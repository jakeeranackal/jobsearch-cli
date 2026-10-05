from datetime import datetime, timedelta

import yaml
from click.testing import CliRunner

from jobsearch import answers, automation, db, interview, keywords, letters, llm, notify, pipeline
from jobsearch.bot import Bot
from jobsearch.cli import cli


def _fake_llm(monkeypatch, text="Subject: Hello\n\nBody text", data=None):
    calls = []
    monkeypatch.setattr(llm, "available", lambda cfg=None: True)
    monkeypatch.setattr(llm, "ask_text", lambda cfg, s, p, **k: calls.append(p) or text)
    monkeypatch.setattr(llm, "ask_json", lambda cfg, s, p, schema, **k: calls.append(p) or data)
    return calls


def test_template_drafts_without_ai(job, resume_text):
    a = keywords.analyze_job(job, resume_text)
    user = {"name": "Jordan Lee", "email": "j@x.com"}
    letter = letters.cover_letter({}, user, job, resume_text, a)
    assert "Acme Health" in letter and "Jordan Lee" in letter
    subj, body = letters.followup_email({}, user, job, "applied", "Sam Park")
    assert "Hi Sam" in body and "Data Analyst" in subj
    subj, body = letters.thank_you_email({}, user, job, "Sam Park", "the Snowflake migration")
    assert "Snowflake migration" in body
    msgs = letters.outreach({}, user, job, a, resume_text, "Priya S")
    assert len(msgs["linkedin"]) <= 300 and "Hi Priya" in msgs["email_body"]


def test_ai_drafts_parse_subject(monkeypatch, job, resume_text):
    calls = _fake_llm(monkeypatch)
    a = keywords.analyze_job(job, resume_text)
    subj, body = letters.followup_email({}, {"name": "J"}, job, "applied")
    assert (subj, body) == ("Hello", "Body text")
    letter = letters.cover_letter({}, {"name": "J", "email": "j@x.com"}, job, resume_text, a)
    assert letter.startswith("J\nj@x.com") and "Body text" in letter
    assert "RESUME" in calls[-1]


def test_answers_render_fills_placeholders(job, resume_text):
    a = keywords.analyze_job(job, resume_text)
    bank = {"salary_expectation": "Targeting {salary_range}.", "why_this_role": "auto",
            "custom": "ignored", "links": {"linkedin": "https://li/j"}}
    text = answers.render(bank, job, {}, resume_text, a)
    assert "$75,000-$95,000" in text
    assert "The Data Analyst role centers on" in text
    assert "https://li/j" in text


def test_prep_sheet_and_salary(job, resume_text):
    a = keywords.analyze_job(job, resume_text)
    stories = [{"title": "Dashboards for ops", "tags": ["tableau", "dashboards"], "result": "x"},
               {"title": "Unrelated", "tags": ["cooking"]}]
    sheet = interview.prep_sheet({}, job, resume_text, a, stories)
    assert "Dashboards for ops" in sheet and "Unrelated" not in sheet
    assert "Walk me through how you've used" in sheet
    assert "$75,000 to $95,000" in interview.salary_help({}, job, a)


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


def test_daily_run_offline_drafts_thank_you(project, job, monkeypatch):
    cfg = yaml.safe_load((project / "config.yaml").read_text())
    with db.connect() as conn:
        db.upsert_job(conn, job)
        start = (datetime.now() - timedelta(hours=3)).isoformat(timespec="minutes")
        conn.execute("INSERT INTO interviews (job_id, starts_at, duration_min, interviewer) "
                     "VALUES (?, ?, 45, 'Sam Park')", (job["id"], start))
    automation.run_daily(cfg, log=lambda m: None)
    assert (project / "applications" / "manual_acme-health_1" / "thank_you.md").exists()
    with db.connect() as conn:
        assert conn.execute("SELECT thanks_drafted FROM interviews").fetchone()[0] == 1


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
