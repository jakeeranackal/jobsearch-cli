"""Gmail: connect, sync replies into statuses, and save emails you wrote as drafts."""
from __future__ import annotations

import sys

import click

from pathlib import Path

from .. import db, google_api, inbox
from ..config import console, load_config


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


@email.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--to", "to_email", required=True)
@click.option("--subject", required=True)
def draft(file: str, to_email: str, subject: str) -> None:
    """Put an email you wrote (FILE) into Gmail Drafts. It is never sent from here."""
    body = Path(file).read_text(encoding="utf-8").strip()
    google_api.create_draft(_gmail_or_exit(), to_email, subject, body)
    console.print(f"[green]Saved to Gmail Drafts[/green] for {to_email}. Review and send it yourself.")


COMMANDS = [email]
