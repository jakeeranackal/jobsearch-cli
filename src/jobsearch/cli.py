"""click-based CLI for jobsearch.

Commands:
    init        Create config.yaml and the SQLite database.
    discover    Pull jobs from every configured source.
    match       Score every open job against every resume track.
    list        Show top matches.
    draft       Generate a cover letter draft for a job.
    track       Update an application's status.
    followup    Show applications due for follow-up.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from . import db, drafter, matcher
from .sources import ashby, greenhouse, lever, rss

CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG = Path("config.example.yaml")
DRAFTS_DIR = Path("drafts")

console = Console()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(
            "[red]No config.yaml found.[/red] Run `jobsearch init` first.",
        )
        sys.exit(1)
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def passes_filters(job: dict, filters: dict) -> bool:
    title = (job.get("title") or "").lower()
    loc = (job.get("location") or "").lower()
    for term in filters.get("exclude_title_terms", []) or []:
        if term.lower() in title:
            return False
    include_locs = filters.get("include_locations") or []
    if include_locs and loc:
        if not any(L.lower() in loc for L in include_locs):
            return False
    return True


@click.group()
def cli() -> None:
    """jobsearch — focused job search command line."""


@cli.command()
def init() -> None:
    """Copy config.example.yaml to config.yaml and create the database."""
    if CONFIG_PATH.exists():
        console.print(f"[yellow]{CONFIG_PATH} already exists — not overwriting.[/yellow]")
    elif EXAMPLE_CONFIG.exists():
        shutil.copy(EXAMPLE_CONFIG, CONFIG_PATH)
        console.print(f"[green]Created {CONFIG_PATH}[/green] — edit it before running discover.")
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
    cfg = load_config()
    filters = cfg.get("filters") or {}
    sources_cfg = cfg.get("sources") or {}

    total_new = 0
    total_seen = 0

    adapters = [
        ("greenhouse", sources_cfg.get("greenhouse") or [], greenhouse.fetch),
        ("lever",      sources_cfg.get("lever")      or [], lever.fetch),
        ("ashby",      sources_cfg.get("ashby")      or [], ashby.fetch),
    ]

    with db.connect() as conn:
        for source_name, slugs, fetcher in adapters:
            for slug in slugs:
                try:
                    jobs = fetcher(slug)
                except Exception as e:  # noqa: BLE001
                    console.print(f"[red]{source_name}:{slug} failed: {e}[/red]")
                    continue
                kept_ids: set[str] = set()
                new_here = 0
                for j in jobs:
                    if not passes_filters(j, filters):
                        continue
                    kept_ids.add(j["id"])
                    if db.upsert_job(conn, j):
                        new_here += 1
                closed = db.mark_jobs_closed(conn, source_name, slug, kept_ids)
                total_new += new_here
                total_seen += len(kept_ids)
                console.print(
                    f"  {source_name}:{slug} — {len(kept_ids)} open, "
                    f"{new_here} new, {closed} closed"
                )

        for feed in sources_cfg.get("rss") or []:
            name, url = feed.get("name"), feed.get("url")
            if not name or not url:
                continue
            try:
                jobs = rss.fetch(name, url)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]rss:{name} failed: {e}[/red]")
                continue
            kept_ids: set[str] = set()
            new_here = 0
            for j in jobs:
                if not passes_filters(j, filters):
                    continue
                kept_ids.add(j["id"])
                if db.upsert_job(conn, j):
                    new_here += 1
            closed = db.mark_jobs_closed(conn, "rss", name, kept_ids)
            total_new += new_here
            total_seen += len(kept_ids)
            console.print(
                f"  rss:{name} — {len(kept_ids)} open, {new_here} new, {closed} closed"
            )

    console.print(f"\n[bold green]Discovered {total_seen} open jobs ({total_new} new).[/bold green]")


@cli.command()
def match() -> None:
    """Score every open job against every configured resume track."""
    cfg = load_config()
    tracks_cfg = cfg.get("resume_tracks") or {}
    if not tracks_cfg:
        console.print("[red]No resume_tracks configured.[/red]")
        sys.exit(1)

    tracks = []
    for name, t in tracks_cfg.items():
        tracks.append(matcher.load_track(name, t["path"], t.get("keywords") or []))

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, description FROM jobs WHERE is_open = 1"
        ).fetchall()
        jobs = [(r["id"], r["title"], r["description"]) for r in rows]

        if not jobs:
            console.print("[yellow]No open jobs in the database. Run `jobsearch discover` first.[/yellow]")
            return

        for track in tracks:
            scores = matcher.score_jobs(track, jobs)
            for job_id, score in scores.items():
                db.record_score(conn, job_id, track.name, score)
            console.print(f"  Scored {len(scores)} jobs against track [bold]{track.name}[/bold]")


@cli.command(name="list")
@click.option("--min-score", default=0.15, type=float, help="Minimum score to show.")
@click.option("--limit", default=25, type=int)
@click.option("--track", default=None, help="Filter to a single resume track.")
def list_cmd(min_score: float, limit: int, track: str | None) -> None:
    """Show top-scoring open jobs."""
    with db.connect() as conn:
        query = """
        SELECT j.id, j.title, j.source_company, j.location, s.track, s.score, j.url
        FROM jobs j
        JOIN scores s ON s.job_id = j.id
        WHERE j.is_open = 1 AND s.score >= ?
        """
        params: list = [min_score]
        if track:
            query += " AND s.track = ?"
            params.append(track)
        query += " ORDER BY s.score DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()

    if not rows:
        console.print("[yellow]No jobs matched. Lower --min-score or run discover/match.[/yellow]")
        return

    table = Table(title=f"Top matches (min score {min_score})")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Track", style="cyan")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Location")
    table.add_column("ID", style="dim")
    for r in rows:
        table.add_row(
            f"{r['score']:.3f}", r["track"], r["title"],
            r["source_company"], r["location"] or "", r["id"],
        )
    console.print(table)


@cli.command()
@click.argument("job_id")
def draft(job_id: str) -> None:
    """Generate a cover letter draft for JOB_ID. The draft is written to ./drafts/."""
    cfg = load_config()
    user = cfg.get("user") or {}
    tracks_cfg = cfg.get("resume_tracks") or {}

    with db.connect() as conn:
        job_row = conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not job_row:
            console.print(f"[red]No job with id {job_id}.[/red]")
            sys.exit(1)
        job = dict(job_row)

        # Pick the best-scoring track for this job
        best = conn.execute(
            "SELECT track, score FROM scores WHERE job_id = ? ORDER BY score DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        if not best:
            console.print(
                f"[red]No score for {job_id}. Run `jobsearch match` first.[/red]"
            )
            sys.exit(1)
        track_name = best["track"]
        score = best["score"]

    track_cfg = tracks_cfg[track_name]
    resume_text = Path(track_cfg["path"]).read_text(encoding="utf-8")
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
def track(job_id: str, status: str, notes: str | None) -> None:
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
    console.print(f"[green]{job_id} -> {status}[/green]")


@cli.command()
def followup() -> None:
    """Show applications whose next_followup_at is in the past."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT a.job_id, a.status, a.applied_at, a.next_followup_at,
                   j.title, j.source_company, j.url, a.notes
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.next_followup_at IS NOT NULL
              AND a.next_followup_at <= ?
              AND a.status NOT IN ('rejected', 'offer', 'withdrawn')
            ORDER BY a.next_followup_at ASC
            """,
            (now,),
        ).fetchall()

    if not rows:
        console.print("[green]Nothing due for follow-up. Nice.[/green]")
        return

    table = Table(title="Follow-ups due")
    table.add_column("Due")
    table.add_column("Status", style="cyan")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Notes", style="dim")
    for r in rows:
        table.add_row(
            (r["next_followup_at"] or "")[:10],
            r["status"], r["title"], r["source_company"], r["notes"] or "",
        )
    console.print(table)


if __name__ == "__main__":
    cli()
