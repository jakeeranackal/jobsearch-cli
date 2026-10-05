"""click-based CLI for jobsearch.

Core:       setup, init, discover, match, list, add, track, applications, followup
Per job:    analyze, prepare, check, export, contacts, ats
Market:     keywords, companies
Email:      email connect/sync/draft
Interviews: interview add/list
Insight:    stats, report, digest

The tool finds, scores, analyzes, tracks and checks. Writing (resume wording,
letters, emails, interview prep) is done by you or Claude Code.
Automation: daily, schedule, dashboard, bot
Network:    network import, referrals
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.table import Table

from . import db, drafter, pipeline, quality, resume_io
from .config import CONFIG_PATH, DRAFTS_DIR, EXAMPLE_CONFIG, company_name, console, load_config
from .pipeline import passes_filters  # noqa: F401  (kept for backward compatibility)


@click.group()
def cli() -> None:
    """jobsearch: focused job search from the command line."""


def _log(msg: str) -> None:
    console.print(msg)


@cli.command()
def init() -> None:
    """Copy config.example.yaml to config.yaml and create the database."""
    if CONFIG_PATH.exists():
        console.print(f"[yellow]{CONFIG_PATH} already exists, not overwriting.[/yellow]")
    elif EXAMPLE_CONFIG.exists():
        shutil.copy(EXAMPLE_CONFIG, CONFIG_PATH)
        console.print(f"[green]Created {CONFIG_PATH}[/green]. Edit it before running discover.")
    else:
        console.print("[red]config.example.yaml is missing.[/red]")
        sys.exit(1)

    db.init_db()
    console.print(f"[green]Initialized {db.DEFAULT_DB}[/green]")

    Path("resumes").mkdir(exist_ok=True)
    Path("drafts").mkdir(exist_ok=True)
    Path("resumes/.gitkeep").touch()
    Path("drafts/.gitkeep").touch()


@cli.command()
def discover() -> None:
    """Pull jobs from every configured source and store new ones."""
    seen, new = pipeline.discover(load_config(), log=_log)
    console.print(f"\n[bold green]Discovered {seen} open jobs ({new} new).[/bold green]")


@cli.command()
def match() -> None:
    """Score every open job against every configured resume track."""
    cfg = load_config()
    if not cfg.get("resume_tracks"):
        console.print("[red]No resume_tracks configured.[/red]")
        sys.exit(1)
    n = pipeline.match(cfg, log=_log)
    if not n:
        console.print("[yellow]No open jobs in the database. Run `jobsearch discover` first.[/yellow]")


@cli.command(name="list")
@click.option("--min-score", default=0.15, type=float, help="Minimum score to show.")
@click.option("--limit", default=25, type=int)
@click.option("--track", default=None, help="Filter to a single resume track.")
@click.option("--fresh", "fresh_days", default=None, type=int, help="Only jobs posted in the last N days.")
@click.option("--min-salary", default=None, type=int, help="Hide jobs whose posted max is below this.")
@click.option("--hide-flagged", is_flag=True, help="Hide staffing agencies, stale and no-salary postings.")
@click.option("--sort", type=click.Choice(["score", "fresh"]), default="score")
@click.option("--show-dups", is_flag=True, help="Include duplicate postings.")
def list_cmd(min_score: float, limit: int, track: str | None, fresh_days: int | None,
             min_salary: int | None, hide_flagged: bool, sort: str, show_dups: bool) -> None:
    """Show top-scoring open jobs."""
    cfg = load_config() if CONFIG_PATH.exists() else {}
    min_salary = min_salary or (cfg.get("search") or {}).get("salary_floor")
    with db.connect() as conn:
        query = """
        SELECT j.*, s.track, s.score
        FROM jobs j
        JOIN scores s ON s.job_id = j.id
        WHERE j.is_open = 1 AND s.score >= ?
        """
        params: list = [min_score]
        if track:
            query += " AND s.track = ?"
            params.append(track)
        if not show_dups:
            query += " AND j.dup_of IS NULL"
        if hide_flagged:
            query += " AND j.flags IS NULL"
        if min_salary:
            query += " AND (j.salary_max IS NULL OR j.salary_max >= ?)"
            params.append(min_salary)
        query += " ORDER BY s.score DESC"
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    best: dict[str, dict] = {}
    for r in rows:
        best.setdefault(r["id"], r)
    rows = list(best.values())
    for r in rows:
        r["age"] = quality.age_days(r)
    if fresh_days is not None:
        rows = [r for r in rows if r["age"] is not None and r["age"] <= fresh_days]
    if sort == "fresh":
        rows.sort(key=lambda r: (r["age"] if r["age"] is not None else 9999, -r["score"]))
    rows = rows[:limit]

    if not rows:
        console.print("[yellow]No jobs matched. Lower --min-score or run discover/match.[/yellow]")
        return

    table = Table(title=f"Top matches (min score {min_score})")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Track", style="cyan")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Location")
    table.add_column("Age", justify="right")
    table.add_column("Salary", justify="right")
    table.add_column("Flags", style="yellow")
    table.add_column("ID", style="dim")
    for r in rows:
        salary = f"{r['salary_min'] // 1000}-{(r['salary_max'] or r['salary_min']) // 1000}k" \
            if r.get("salary_min") else ""
        table.add_row(
            f"{r['score']:.3f}", r["track"], r["title"], company_name(r), r["location"] or "",
            f"{r['age']}d" if r["age"] is not None else "", salary, r.get("flags") or "", r["id"],
        )
    console.print(table)


@cli.command()
@click.argument("job_id")
def draft(job_id: str) -> None:
    """Template cover letter for JOB_ID, written to ./drafts/. See also `letter` and `apply`."""
    cfg = load_config()
    user = cfg.get("user") or {}
    tracks_cfg = cfg.get("resume_tracks") or {}

    with db.connect() as conn:
        job = db.get_job(conn, job_id)
        if not job:
            console.print(f"[red]No job with id {job_id}.[/red]")
            sys.exit(1)
        best = db.best_track(conn, job_id)
        if not best:
            console.print(f"[red]No score for {job_id}. Run `jobsearch match` first.[/red]")
            sys.exit(1)
        track_name, score = best

    track_cfg = tracks_cfg[track_name]
    resume_text = resume_io.read_text(track_cfg["path"])
    keywords = [k.lower() for k in (track_cfg.get("keywords") or [])]
    desc_l = (job["title"] + " " + job["description"]).lower()
    matched = [k for k in keywords if k in desc_l]

    body = drafter.render(
        user=user,
        job=job,
        resume_track=track_name,
        score=score,
        matched_keywords=matched,
        resume_highlights=drafter.extract_highlights(resume_text),
    )
    path = drafter.save(DRAFTS_DIR, job_id, body)

    with db.connect() as conn:
        db.update_application(
            conn, job_id, "drafted",
            followup_days=cfg.get("followup_days") or {},
            resume_track=track_name,
            cover_letter_path=str(path),
        )

    console.print(f"[green]Draft written:[/green] {path}")
    console.print(f"[dim]Track: {track_name}  •  Score: {score:.3f}  •  Matched keywords: {', '.join(matched) or 'none'}[/dim]")
    console.print("[yellow]Review and customize the marked paragraphs before sending.[/yellow]")


@cli.command()
@click.argument("job_id")
@click.option("--status", required=True,
              type=click.Choice(["drafted", "applied", "interviewing", "rejected", "offer", "withdrawn"]))
@click.option("--notes", default=None)
@click.option("--contact-email", default=None, help="Recruiter/hiring manager email for follow-ups.")
def track(job_id: str, status: str, notes: str | None, contact_email: str | None) -> None:
    """Update the application status for JOB_ID."""
    cfg = load_config()
    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not exists:
            console.print(f"[red]No job with id {job_id}.[/red]")
            sys.exit(1)
        db.update_application(
            conn, job_id, status,
            followup_days=cfg.get("followup_days") or {},
            notes=notes,
        )
        if contact_email:
            conn.execute("UPDATE applications SET contact_email = ? WHERE job_id = ?",
                         (contact_email, job_id))
    console.print(f"[green]{job_id} -> {status}[/green]")


@cli.command(name="applications")
@click.option("--status", default=None,
              type=click.Choice(["drafted", "applied", "interviewing", "rejected", "offer", "withdrawn"]))
def applications_cmd(status: str | None) -> None:
    """Every application you're tracking, with status and next follow-up."""
    with db.connect() as conn:
        sql = """SELECT a.*, j.title, j.source_company, j.company_name, j.url
                 FROM applications a JOIN jobs j ON j.id = a.job_id"""
        params: list = []
        if status:
            sql += " WHERE a.status = ?"
            params.append(status)
        sql += " ORDER BY COALESCE(a.next_followup_at, '9999'), a.last_update_at DESC"
        rows = [dict(r) for r in conn.execute(sql, params)]
    if not rows:
        console.print("[yellow]No applications tracked yet.[/yellow]")
        return
    table = Table(title=f"Applications ({len(rows)})")
    for col in ("Status", "Title", "Company", "Applied", "Next follow-up", "Notes", "ID"):
        table.add_column(col, style="dim" if col == "ID" else None)
    for r in rows:
        table.add_row(r["status"], r["title"], company_name(r), (r["applied_at"] or "")[:10],
                      (r["next_followup_at"] or "")[:10], r["notes"] or "", r["job_id"])
    console.print(table)


def due_followups(conn) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [dict(r) for r in conn.execute(
        """
        SELECT a.job_id, a.status, a.applied_at, a.next_followup_at, a.contact_email,
               j.title, j.source_company, j.company_name, j.url, a.notes
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        WHERE a.next_followup_at IS NOT NULL
          AND a.next_followup_at <= ?
          AND a.status NOT IN ('rejected', 'offer', 'withdrawn')
        ORDER BY a.next_followup_at ASC
        """,
        (now,),
    ).fetchall()]


@cli.command()
def followup() -> None:
    """Show applications whose next_followup_at is in the past."""
    with db.connect() as conn:
        rows = due_followups(conn)

    if not rows:
        console.print("[green]Nothing due for follow-up. Nice.[/green]")
        return

    table = Table(title="Follow-ups due")
    table.add_column("Due")
    table.add_column("Status", style="cyan")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Contact")
    table.add_column("Notes", style="dim")
    for r in rows:
        table.add_row(
            (r["next_followup_at"] or "")[:10],
            r["status"], r["title"], company_name(r), r["contact_email"] or "", r["notes"] or "",
        )
    console.print(table)


def _register() -> None:
    from .commands import apply, automation, email, find, insights, interviews, network, setup

    for module in (setup, find, apply, email, interviews, insights, automation, network):
        for command in module.COMMANDS:
            cli.add_command(command)


_register()


if __name__ == "__main__":
    cli()
