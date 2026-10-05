"""Interviews: log them, and add them to Google Calendar when connected."""
from __future__ import annotations

import sys
from datetime import datetime

import click
from rich.table import Table

from .. import db, google_api
from ..config import company_name, console, load_config


@click.group(name="interview")
def interview_group() -> None:
    """Track interviews; adds them to Google Calendar when connected."""


@interview_group.command(name="add")
@click.argument("job_id")
@click.option("--when", required=True, help='Local time, e.g. "2026-10-14 14:00".')
@click.option("--minutes", default=45, type=int)
@click.option("--with", "interviewer", default=None, help="Interviewer name.")
@click.option("--email", "interviewer_email", default=None)
def interview_add(job_id: str, when: str, minutes: int, interviewer: str | None,
                  interviewer_email: str | None) -> None:
    """Log an interview, mark the application interviewing, add a calendar event."""
    cfg = load_config()
    try:
        start = datetime.fromisoformat(when)
    except ValueError:
        console.print('[red]Use a time like "2026-10-14 14:00".[/red]')
        sys.exit(1)
    event_id = None
    with db.connect() as conn:
        job = db.get_job(conn, job_id)
        if not job:
            console.print(f"[red]No job with id {job_id}.[/red]")
            sys.exit(1)
        if google_api.is_configured():
            tz = (cfg.get("user") or {}).get("timezone") or "America/New_York"
            event_id = google_api.create_event(
                google_api.calendar(), f"Interview: {job['title']} at {company_name(job)}",
                start, minutes, f"{job['url']}\nWith: {interviewer or 'TBD'}", timezone=tz)
        conn.execute(
            "INSERT INTO interviews (job_id, starts_at, duration_min, interviewer, interviewer_email, "
            "calendar_event_id) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, start.isoformat(timespec="minutes"), minutes, interviewer, interviewer_email, event_id),
        )
        app = db.get_application(conn, job_id)
        if not app or app["status"] in ("drafted", "applied"):
            db.update_application(conn, job_id, "interviewing", followup_days=cfg.get("followup_days") or {})
    console.print(f"[green]Interview logged[/green] for {start:%a %b %d %I:%M %p}.")
    if event_id:
        console.print("[green]Added to Google Calendar[/green] with reminders 1 day and 1 hour before.")


@interview_group.command(name="list")
def interview_list() -> None:
    """Upcoming and recent interviews."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT i.*, j.title, j.source_company, j.company_name FROM interviews i
               JOIN jobs j ON j.id = i.job_id ORDER BY i.starts_at DESC LIMIT 30""").fetchall()
    table = Table(title="Interviews")
    for col in ("When", "Role", "With", "ID"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["starts_at"], f"{r['title']} at {company_name(dict(r))}",
                      r["interviewer"] or "", r["job_id"])
    console.print(table)


COMMANDS = [interview_group]
