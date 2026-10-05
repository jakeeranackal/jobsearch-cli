"""Funnel stats: what's actually getting responses, plus the weekly report."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .quality import _parse_date

RESPONDED = {"interviewing", "rejected", "offer"}
CALLBACK = {"interviewing", "offer"}


@dataclass
class Bucket:
    applied: int = 0
    responded: int = 0
    callbacks: int = 0

    @property
    def response_rate(self) -> float:
        return self.responded / self.applied if self.applied else 0.0

    @property
    def callback_rate(self) -> float:
        return self.callbacks / self.applied if self.applied else 0.0


def _applications(conn: sqlite3.Connection) -> list[dict]:
    rows = [dict(r) for r in conn.execute(
        """SELECT a.*, j.source, j.posted_at, j.discovered_at, j.title, j.source_company
           FROM applications a JOIN jobs j ON j.id = a.job_id""")]
    history = defaultdict(set)
    for r in conn.execute("SELECT job_id, status FROM status_history"):
        history[r["job_id"]].add(r["status"])
    for r in rows:
        statuses = history[r["job_id"]] | {r["status"]}
        r["was_applied"] = bool(statuses & ({"applied"} | RESPONDED)) or bool(r["applied_at"])
        r["responded"] = bool(statuses & RESPONDED)
        r["callback"] = bool(statuses & CALLBACK)
    return [r for r in rows if r["was_applied"]]


def _days_bucket(app: dict) -> str:
    posted = _parse_date(app.get("posted_at")) or _parse_date(app.get("discovered_at"))
    applied = _parse_date(app.get("applied_at"))
    if not posted or not applied:
        return "unknown"
    d = (applied - posted).days
    return "0-2 days" if d <= 2 else "3-7 days" if d <= 7 else "8-14 days" if d <= 14 else "15+ days"


def funnel(conn: sqlite3.Connection) -> dict[str, dict[str, Bucket]]:
    apps = _applications(conn)
    groups: dict[str, dict[str, Bucket]] = {
        "overall": defaultdict(Bucket), "resume track": defaultdict(Bucket),
        "tailored resume": defaultdict(Bucket), "source": defaultdict(Bucket),
        "applied after posting": defaultdict(Bucket),
    }
    for a in apps:
        keys = {
            "overall": "all",
            "resume track": a.get("resume_track") or "none",
            "tailored resume": "tailored" if a.get("resume_path") else "not tailored",
            "source": a.get("source") or "?",
            "applied after posting": _days_bucket(a),
        }
        for group, key in keys.items():
            b = groups[group][key]
            b.applied += 1
            b.responded += a["responded"]
            b.callbacks += a["callback"]
    return {g: dict(v) for g, v in groups.items()}


def weekly(conn: sqlite3.Connection, days: int = 7, target: int = 10) -> str:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    q = lambda sql: conn.execute(sql, (since,)).fetchone()[0]  # noqa: E731
    new_jobs = q("SELECT COUNT(*) FROM jobs WHERE discovered_at >= ?")
    changes = defaultdict(int)
    for r in conn.execute("SELECT status, COUNT(*) n FROM status_history WHERE at >= ? GROUP BY status", (since,)):
        changes[r["status"]] = r["n"]
    due = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE next_followup_at <= ? "
        "AND status NOT IN ('rejected','offer','withdrawn')",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),)).fetchone()[0]

    lines = [f"Job search: last {days} days", "",
             f"New jobs found: {new_jobs}",
             f"Applications sent: {changes['applied']}",
             f"Interviews: {changes['interviewing']}",
             f"Rejections: {changes['rejected']}",
             f"Offers: {changes['offer']}",
             f"Follow-ups due now: {due}", ""]

    tips = []
    if changes["applied"] < target:
        tips.append(f"Send {target - changes['applied']} more applications to hit your weekly target of {target}.")
    f = funnel(conn)
    tailored = f["tailored resume"].get("tailored")
    plain = f["tailored resume"].get("not tailored")
    if tailored and plain and tailored.applied >= 3 and plain.applied >= 3:
        if tailored.callback_rate > plain.callback_rate:
            tips.append(f"Tailored resumes get {tailored.callback_rate:.0%} callbacks vs "
                        f"{plain.callback_rate:.0%} untailored. Tailor every application.")
    early = f["applied after posting"].get("0-2 days")
    late = f["applied after posting"].get("8-14 days") or f["applied after posting"].get("15+ days")
    if early and late and early.applied >= 3 and late.applied >= 3 and early.callback_rate > late.callback_rate:
        tips.append(f"Applying within 2 days: {early.callback_rate:.0%} callbacks vs "
                    f"{late.callback_rate:.0%} later. Check the digest daily.")
    if due:
        tips.append(f"Run `jobsearch followup --draft` to queue {due} follow-up email(s).")
    if tips:
        lines += ["What to do next:"] + [f"- {t}" for t in tips]
    return "\n".join(lines)
