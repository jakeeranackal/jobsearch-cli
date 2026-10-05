from datetime import datetime, timedelta, timezone

from jobsearch import db, inbox, network, quality, stats


def _msg(subject, body, sender="jobs@acmehealth.com", name="Acme Health Recruiting", mid="m1"):
    return {"id": mid, "from_name": name, "from_email": sender, "subject": subject,
            "date": "2026-10-05T10:00:00", "snippet": body[:100], "body": body}


def test_classify_rules():
    assert inbox.classify("Your application", "Unfortunately we will not be moving forward") == "rejection"
    assert inbox.classify("Next steps", "Please share your availability for a phone screen") == "interview"
    assert inbox.classify("Offer", "We are pleased to offer you the role") == "offer"
    assert inbox.classify("Thanks", "We received your application") == "ack"
    assert inbox.classify("Newsletter", "Our product update") == "other"


def test_sync_moves_status_forward_never_back(project, job):
    with db.connect() as conn:
        db.upsert_job(conn, job)
        db.update_application(conn, job["id"], "applied", followup_days={})
        events = inbox.sync(conn, [_msg("Interview", "Can we schedule a call? Your availability?")])
        assert events[0]["change"] == ("applied", "interviewing")
        assert db.get_application(conn, job["id"])["status"] == "interviewing"
        assert db.get_application(conn, job["id"])["contact_email"] == "jobs@acmehealth.com"
        # An acknowledgement afterwards doesn't move it back
        inbox.sync(conn, [_msg("Thanks", "We received your application", mid="m2")])
        assert db.get_application(conn, job["id"])["status"] == "interviewing"
        # Same message twice is ignored
        assert inbox.sync(conn, [_msg("Interview", "schedule a call", mid="m1")]) == []


def test_unrelated_email_not_matched(project, job):
    with db.connect() as conn:
        db.upsert_job(conn, job)
        db.update_application(conn, job["id"], "applied", followup_days={})
        assert inbox.sync(conn, [_msg("Hi", "unfortunately", sender="a@b.com", name="Bob")]) == []


def test_quality_flags_and_dedupe(project, job):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    agency = {**job, "id": "manual:x:2", "description": "Our client is hiring. " + job["description"],
              "posted_at": old}
    dup = {**job, "id": "manual:acme-health:3"}
    with db.connect() as conn:
        for j in (job, agency, dup):
            db.upsert_job(conn, j)
        counts = quality.refresh(conn)
        rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM jobs")}
    assert counts["duplicates"] >= 1
    assert rows["manual:acme-health:3"]["dup_of"] == job["id"]
    assert "staffing agency" in rows["manual:x:2"]["flags"]
    assert "open 90d" in rows["manual:x:2"]["flags"]
    assert rows[job["id"]]["salary_min"] == 75000


def test_no_salary_flag_in_pay_transparency_state():
    f = quality.flags({"title": "x", "location": "Denver, CO", "description": "no pay"})
    assert "no salary (CO requires one)" in f


def test_linkedin_import_and_referrals(project, tmp_path):
    csv_path = tmp_path / "Connections.csv"
    csv_path.write_text(
        "Notes:\n\"export note\"\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
        "Priya,S,https://li/p,,Acme Health Inc.,Analytics Manager,01 Jan 2025\n"
        "Tom,B,https://li/t,,Acme Healthcare Partners,Engineer,02 Jan 2025\n"
        "Ann,C,https://li/a,,Other,PM,03 Jan 2025\n", encoding="utf-8")
    with db.connect() as conn:
        assert network.import_linkedin_csv(conn, csv_path) == 3
        names = {r["name"] for r in network.referrals(conn, "Acme Health")}
    assert "Priya S" in names and "Ann C" not in names


def test_funnel_counts(project, job):
    with db.connect() as conn:
        db.upsert_job(conn, job)
        db.update_application(conn, job["id"], "applied", followup_days={})
        db.update_application(conn, job["id"], "interviewing", followup_days={})
        f = stats.funnel(conn)
    b = f["overall"]["all"]
    assert (b.applied, b.responded, b.callbacks) == (1, 1, 1)
