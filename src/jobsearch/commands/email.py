"""Gmail: connect, sync inbox into statuses, follow-up and thank-you drafts."""
from __future__ import annotations

import sys

import click

from .. import db, google_api, inbox, letters
from ..config import application_dir, company_name, console, load_config


def _gmail_or_exit():
    try:
        return google_api.gmail()
    except google_api.GoogleNotConfigured as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)


@click.group()
def email() -> None:
    """Gmail integration (optional). Setup steps: `jobsearch email connect --help`."""


@email.command()
def connect() -> None:
    """Sign in to Gmail + Calendar.

    \b
    One-time Google setup (about 5 minutes):
    1. console.cloud.google.com, create a project
    2. Enable "Gmail API" and "Google Calendar API"
    3. OAuth consent screen: External, add your address as a test user
    4. Credentials, Create OAuth client ID, Desktop app, Download JSON
    5. Save it as .secrets/google_credentials.json and rerun this command
    """
    try:
        address = google_api.connect()
    except google_api.GoogleNotConfigured as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    console.print(f"[green]Connected as {address}.[/green] Token saved in .secrets/ (gitignored).")


@email.command()
@click.option("--days", default=14, type=int, help="How far back to read.")
@click.option("--dry-run", is_flag=True, help="Show what would change without saving.")
def sync(days: int, dry_run: bool) -> None:
    """Read recruiter emails and update application statuses automatically."""
    cfg = load_config()
    messages = google_api.recent_messages(_gmail_or_exit(), days=days)
    with db.connect() as conn:
        events = inbox.sync(conn, messages, cfg.get("followup_days") or {}, dry_run=dry_run)
    if not events:
        console.print(f"Read {len(messages)} emails; none matched your applications.")
        return
    for e in events:
        change = f"  [bold]{e['change'][0]} to {e['change'][1]}[/bold]" if e["change"] else ""
        console.print(f"[cyan]{e['label']:10}[/cyan] {e['title']} at {e['company']}: {e['subject'][:70]}{change}")
    if dry_run:
        console.print("[dim]Dry run, nothing saved.[/dim]")


def queue_followups(cfg: dict, rows: list[dict], send: bool = False) -> None:
    """Draft (or send, with confirmation) a follow-up for each due application."""
    user = cfg.get("user") or {}
    auto_send = bool((cfg.get("email") or {}).get("auto_send_followups"))
    service = google_api.gmail() if google_api.is_configured() else None
    with db.connect() as conn:
        for r in rows:
            job = db.get_job(conn, r["job_id"])
            subject, body = letters.followup_email(user, job)
            to = r.get("contact_email")
            path = application_dir(r["job_id"]) / "followup.md"
            path.write_text(f"To: {to or '[ADD recipient]'}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
            label = f"{job['title']} at {company_name(job)}"
            if not service or not to:
                console.print(f"  [yellow]{label}:[/yellow] draft saved to {path}"
                              + ("" if to else " (no contact email; add one with `track --contact-email`)"))
                continue
            if send and (auto_send or click.confirm(f"Send follow-up to {to} for {label}?", default=False)):
                google_api.send(service, to, subject, body)
                console.print(f"  [green]Sent[/green] to {to}: {label}")
            else:
                google_api.create_draft(service, to, subject, body)
                console.print(f"  [green]Gmail draft created[/green] for {label}")
            # Push the next reminder out so the same follow-up isn't drafted daily.
            db.update_application(conn, r["job_id"], r["status"], followup_days=cfg.get("followup_days") or {})


@click.command()
@click.argument("job_id")
@click.option("--to", "to_email", default=None, help="Interviewer's email.")
@click.option("--name", "interviewer", default=None, help="Interviewer's name.")
@click.option("--notes", default=None, help="Something specific you talked about.")
def thanks(job_id: str, to_email: str | None, interviewer: str | None, notes: str | None) -> None:
    """Draft a thank-you note after an interview (Gmail draft if connected)."""
    cfg = load_config()
    with db.connect() as conn:
        job = db.get_job(conn, job_id)
    if not job:
        console.print(f"[red]No job with id {job_id}.[/red]")
        sys.exit(1)
    subject, body = letters.thank_you_email(cfg.get("user") or {}, job, interviewer, notes)
    path = application_dir(job_id) / "thank_you.md"
    path.write_text(f"To: {to_email or '[ADD]'}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    if to_email and google_api.is_configured():
        google_api.create_draft(google_api.gmail(), to_email, subject, body)
        console.print("[green]Gmail draft created.[/green] Review and send within 24 hours.")
    console.print(f"\nSubject: {subject}\n\n{body}\n\n[green]Saved[/green] {path}")


COMMANDS = [email, thanks]
