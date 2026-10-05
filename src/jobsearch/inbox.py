"""Read recruiter emails, match them to applications, and update status.

Classification is keyword rules first (fast, free, explainable). Claude is
only asked about emails the rules can't place, and only if enabled.
"""
from __future__ import annotations

import re
import sqlite3

from . import llm
from .quality import norm

RULES = [
    ("offer", re.compile(r"\b(pleased to offer|offer letter|extend (you )?an offer|formal offer)\b", re.I)),
    ("rejection", re.compile(
        r"(unfortunately|not (be )?moving forward|move forward with other|other candidates|"
        r"decided to (pursue|proceed)|position has been filled|no longer (being )?considered|"
        r"not selected|will not be proceeding|regret to inform)", re.I)),
    ("interview", re.compile(
        r"(schedule (a|an|your) (call|interview|chat|time)|phone screen|interview|"
        r"your availability|calendly\.com|goodtime\.io|next steps? in (the|our) process|"
        r"would love to (chat|connect|speak))", re.I)),
    ("ack", re.compile(
        r"(received your application|thank(s| you) for (applying|your application|your interest)|"
        r"application (has been )?(received|submitted))", re.I)),
]
# An email can move an application forward, never backward (offer beats interview).
RANK = {"drafted": 0, "applied": 1, "interviewing": 2, "rejected": 3, "offer": 4, "withdrawn": 5}
TARGET_STATUS = {"rejection": "rejected", "interview": "interviewing", "offer": "offer"}


def classify(subject: str, body: str, cfg: dict | None = None) -> str:
    text = f"{subject}\n{body}"
    for label, rx in RULES:
        if rx.search(text):
            # "Unfortunately" inside an interview invite ("unfortunately I'm out Friday")
            if label == "rejection" and RULES[2][1].search(subject):
                return "interview"
            return label
    if cfg and (cfg.get("email") or {}).get("ai_classify") and llm.available(cfg):
        schema = {"type": "object", "properties": {"label": {"type": "string", "enum": [
            "offer", "rejection", "interview", "ack", "other"]}}, "required": ["label"],
            "additionalProperties": False}
        out = llm.ask_json(cfg, "Classify job-application emails.",
                           f"Subject: {subject}\n\n{body[:3000]}", schema, effort="low")
        return out["label"]
    return "other"


def match_job(msg: dict, apps: list[dict]) -> dict | None:
    """Find the application this email is about, by company name in sender/subject/body."""
    domain = msg["from_email"].split("@")[-1]
    hay = norm(f"{msg['from_name']} {domain.replace('.', ' ')} {msg['subject']} {msg['body'][:1500]}")
    hay_words = f" {hay} "
    best = None
    for app in apps:
        company = norm(app.get("company_name") or app["source_company"])
        if company and f" {company} " in hay_words:
            # Prefer a job whose title is also mentioned
            if norm(app["title"]) in hay:
                return app
            best = best or app
    return best


def sync(conn: sqlite3.Connection, messages: list[dict], cfg: dict | None = None,
         followup_days: dict | None = None, dry_run: bool = False) -> list[dict]:
    from . import db

    apps = [dict(r) for r in conn.execute(
        """SELECT a.job_id, a.status, j.title, j.source_company, j.company_name
           FROM applications a JOIN jobs j ON j.id = a.job_id
           WHERE a.status NOT IN ('withdrawn')""")]
    seen = {r["message_id"] for r in conn.execute("SELECT message_id FROM emails")}
    events = []
    for msg in messages:
        if msg["id"] in seen:
            continue
        app = match_job(msg, apps)
        if not app:
            continue
        label = classify(msg["subject"], msg["body"] or msg["snippet"], cfg)
        new_status = TARGET_STATUS.get(label)
        change = None
        if new_status and RANK[new_status] > RANK.get(app["status"], 0):
            change = (app["status"], new_status)
        events.append({"job_id": app["job_id"], "title": app["title"],
                       "company": app.get("company_name") or app["source_company"],
                       "subject": msg["subject"], "label": label, "change": change})
        if dry_run:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO emails (message_id, job_id, sender, subject, received_at, classification) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg["id"], app["job_id"], msg["from_email"], msg["subject"], msg["date"], label),
        )
        if change:
            db.update_application(conn, app["job_id"], new_status,
                                  followup_days=followup_days or {},
                                  notes=f"Auto from email: {msg['subject'][:120]}")
            app["status"] = new_status
            if msg["from_email"] and not msg["from_email"].startswith(("no-reply", "noreply", "do-not-reply")):
                conn.execute("UPDATE applications SET contact_email = COALESCE(contact_email, ?) "
                             "WHERE job_id = ?", (msg["from_email"], app["job_id"]))
    return events
