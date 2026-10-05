"""Interviews: schedule (with calendar), prep sheets, mock interviews, salary."""
from __future__ import annotations

import sys
from datetime import datetime

import click
from rich.table import Table

from .. import db, google_api, interview, keywords, llm, pipeline
from ..config import application_dir, company_name, console, load_config


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
    """Log an interview, build the prep sheet, and add a calendar event."""
    cfg = load_config()
    try:
        start = datetime.fromisoformat(when)
    except ValueError:
        console.print('[red]Use a time like "2026-10-14 14:00".[/red]')
        sys.exit(1)
    prep_path = pipeline.prep(cfg, job_id)
    event_id = None
    with db.connect() as conn:
        job = db.get_job(conn, job_id)
        if google_api.is_configured():
            tz = (cfg.get("user") or {}).get("timezone") or "America/New_York"
            desc = f"{job['url']}\n\nPrep sheet: {prep_path.resolve()}\n\n" + prep_path.read_text(encoding="utf-8")[:6000]
            event_id = google_api.create_event(google_api.calendar(),
                                               f"Interview: {job['title']} at {company_name(job)}",
                                               start, minutes, desc, timezone=tz)
        conn.execute(
            "INSERT INTO interviews (job_id, starts_at, duration_min, interviewer, interviewer_email, "
            "calendar_event_id) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, start.isoformat(timespec="minutes"), minutes, interviewer, interviewer_email, event_id),
        )
        app = db.get_application(conn, job_id)
        if not app or app["status"] in ("drafted", "applied"):
            db.update_application(conn, job_id, "interviewing", followup_days=cfg.get("followup_days") or {})
    console.print(f"[green]Interview logged[/green] for {start:%a %b %d %I:%M %p}. Prep sheet: {prep_path}")
    if event_id:
        console.print("[green]Added to Google Calendar[/green] with reminders 1 day and 1 hour before.")
    console.print("A thank-you draft is created automatically after it ends (via `jobsearch daily`).")


@interview_group.command(name="list")
def interview_list() -> None:
    """Upcoming and recent interviews."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT i.*, j.title, j.source_company, j.company_name FROM interviews i
               JOIN jobs j ON j.id = i.job_id ORDER BY i.starts_at DESC LIMIT 30""").fetchall()
    table = Table(title="Interviews")
    for col in ("When", "Role", "With", "Thank-you"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["starts_at"], f"{r['title']} at {company_name(dict(r))}",
                      r["interviewer"] or "", "drafted" if r["thanks_drafted"] else "")
    console.print(table)


@click.command()
@click.argument("job_id")
def prep(job_id: str) -> None:
    """Interview prep sheet: what they'll probe, your proof, stories, likely questions."""
    path = pipeline.prep(load_config(), job_id)
    console.print(path.read_text(encoding="utf-8"))
    console.print(f"[green]Saved[/green] {path}")


@click.command()
@click.argument("job_id")
@click.option("--questions", "n", default=5, type=int)
def mock(job_id: str, n: int) -> None:
    """Practice interview: Claude asks, you answer, you get graded feedback."""
    cfg = load_config()
    if not llm.available(cfg):
        console.print("[red]Mock interviews need a Claude API key (ANTHROPIC_API_KEY).[/red]")
        sys.exit(1)
    with db.connect() as conn:
        job, best, _ = pipeline.job_and_track(conn, job_id)
    _, resume_text = pipeline.resume_for(cfg, best)
    asked: list[str] = []
    log = [f"# Mock interview: {job['title']} at {company_name(job)}", ""]
    console.print("[dim]Answer out loud first, then type it. Enter a blank line to finish an answer; 'q' to stop.[/dim]")
    for i in range(n):
        q = interview.mock_question(cfg, job, resume_text, asked)
        asked.append(q)
        console.print(f"\n[bold cyan]Q{i + 1}.[/bold cyan] {q}")
        lines = []
        while True:
            line = input("> ")
            if line.strip().lower() == "q":
                n = 0
                break
            if not line.strip():
                break
            lines.append(line)
        if not lines:
            break
        answer = " ".join(lines)
        fb = interview.mock_feedback(cfg, job, q, answer)
        console.print(f"\n{fb}")
        log += [f"## Q{i + 1}. {q}", "", f"**Your answer:** {answer}", "", fb, ""]
        if n == 0:
            break
    path = application_dir(job_id) / f"mock_{datetime.now():%Y%m%d_%H%M}.md"
    path.write_text("\n".join(log), encoding="utf-8")
    console.print(f"\n[green]Session saved[/green] {path}")


@click.command()
@click.argument("job_id")
def salary(job_id: str) -> None:
    """Salary range, what to ask for, and negotiation scripts."""
    cfg = load_config()
    with db.connect() as conn:
        job, best, _ = pipeline.job_and_track(conn, job_id)
    _, resume_text = pipeline.resume_for(cfg, best)
    a = keywords.analyze_job(job, resume_text, pipeline.extra_terms(cfg))
    text = interview.salary_help(cfg, job, a, (cfg.get("user") or {}).get("location") or "")
    path = application_dir(job_id) / "salary.md"
    path.write_text(text, encoding="utf-8")
    console.print(text)


COMMANDS = [interview_group, prep, mock, salary]
