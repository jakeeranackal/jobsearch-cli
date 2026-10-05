"""Finding jobs: add by hand, keyword cloud across listings, companies to watch, digest."""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import click
from rich.table import Table

from .. import company, db, keywords, pipeline, quality
from ..config import console, load_config, save_config
from ..sources import manual


@click.command()
@click.option("--paste", "paste", is_flag=True, help="Open an editor to paste a listing (LinkedIn, Indeed...).")
@click.option("--file", "file_", type=click.Path(exists=True, dir_okay=False), help="Listing text file.")
@click.option("--url", default=None, help="Posting URL (works best for Greenhouse/Lever/etc links).")
@click.option("--title", default=None)
@click.option("--company", "company_", default=None)
@click.option("--location", default=None)
def add(paste: bool, file_: str | None, url: str | None, title: str | None,
        company_: str | None, location: str | None) -> None:
    """Add one job by pasting it, from a file, or from a URL. Then scores it."""
    cfg = load_config()
    job: dict | None = None
    if url and not manual.is_blocked(url):
        try:
            job = manual.fetch_url(url)
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]Couldn't fetch {url} ({e}). Paste the text instead.[/yellow]")
    elif url:
        console.print("[yellow]LinkedIn/Indeed pages can't be fetched. Paste the listing text instead.[/yellow]")
        paste = True

    if job is None or not job.get("description"):
        if file_:
            text = Path(file_).read_text(encoding="utf-8", errors="replace")
        elif paste or not url:
            text = click.edit("\n# Paste the full job listing above this line, save, and close.\n") or ""
            text = text.split("\n# Paste the full job listing")[0]
        else:
            text = ""
        if not text.strip():
            console.print("[red]No listing text given.[/red]")
            sys.exit(1)
        job = {"description": text, "url": url or ""}

    if "id" not in job:
        title = title or click.prompt("Job title", default=job.get("title") or "")
        company_ = company_ or click.prompt("Company")
        job = manual.from_text(job["description"], title=title, company=company_,
                               location=location, url=job.get("url") or "")

    with db.connect() as conn:
        is_new = db.upsert_job(conn, job)
        quality.refresh(conn)
    pipeline.match(cfg, log=lambda m: None)
    with db.connect() as conn:
        best = db.best_track(conn, job["id"])
    state = "Added" if is_new else "Already had"
    score = f" (score {best[1]:.2f} on {best[0]})" if best else ""
    console.print(f"[green]{state}:[/green] {job['title']}{score}\n  id: [bold]{job['id']}[/bold]")
    console.print(f"  Next: `jobsearch analyze {job['id']}` or `jobsearch apply {job['id']}`")


@click.command(name="keywords")
@click.option("--title", "title_filter", default=None, help="Only postings whose title contains this.")
@click.option("--min-score", default=None, type=float, help="Only postings scoring at least this.")
@click.option("--file", "files", multiple=True, type=click.Path(exists=True),
              help="Text file(s) of pasted listings, separated by a line of ===.")
@click.option("--top", default=30, type=int)
@click.option("--cloud", "cloud_path", default=None, help="Write an HTML word cloud here and open it.")
@click.option("--track", default=None, help="Resume track to compare against.")
def keywords_cmd(title_filter: str | None, min_score: float | None, files: tuple[str, ...],
                 top: int, cloud_path: str | None, track: str | None) -> None:
    """The big words across many listings, and which ones your resume is missing."""
    cfg = load_config()
    jobs: list[dict] = []
    for f in files:
        for chunk in Path(f).read_text(encoding="utf-8", errors="replace").split("\n==="):
            if chunk.strip():
                jobs.append({"title": "", "description": chunk})
    if not files:
        with db.connect() as conn:
            sql = "SELECT j.* FROM jobs j WHERE j.is_open = 1 AND j.dup_of IS NULL"
            params: list = []
            if title_filter:
                sql += " AND LOWER(j.title) LIKE ?"
                params.append(f"%{title_filter.lower()}%")
            if min_score is not None:
                sql += " AND j.id IN (SELECT job_id FROM scores WHERE score >= ?)"
                params.append(min_score)
            jobs = [dict(r) for r in conn.execute(sql, params)]
    if not jobs:
        console.print("[yellow]No postings to analyze. Run discover, or pass --file.[/yellow]")
        return
    _, resume_text = pipeline.resume_for(cfg, track)
    terms, phrases = keywords.market_terms(jobs, resume_text, pipeline.extra_terms(cfg))

    table = Table(title=f"Most-wanted terms across {len(jobs)} postings")
    table.add_column("Term")
    table.add_column("In postings", justify="right")
    table.add_column("Required in", justify="right")
    table.add_column("Share", justify="right")
    table.add_column("Your resume")
    for t in terms[:top]:
        table.add_row(t.term, str(t.jobs_mentioning), str(t.jobs_requiring), f"{t.share:.0%}",
                      "[green]yes[/green]" if t.on_resume else "[red]missing[/red]")
    console.print(table)
    missing = [t.term for t in terms[:top] if not t.on_resume and t.share >= 0.2]
    if missing:
        console.print(f"[bold]In 20%+ of postings but not on your resume:[/bold] {', '.join(missing)}")
    if phrases:
        console.print("[dim]Other repeated phrases: " + ", ".join(p for p, _ in phrases[:15]) + "[/dim]")
    if cloud_path:
        out = Path(cloud_path)
        out.write_text(keywords.cloud_html(terms, phrases, len(jobs)), encoding="utf-8")
        console.print(f"[green]Word cloud:[/green] {out}")
        webbrowser.open(out.resolve().as_uri())


@click.group()
def companies() -> None:
    """Companies to watch: add by careers URL, or list them."""


@companies.command(name="add")
@click.argument("urls", nargs=-1, required=True)
def companies_add(urls: tuple[str, ...]) -> None:
    """Add companies by careers-page URL (Greenhouse, Lever, Ashby, Workday, ...)."""
    cfg = load_config()
    sources = cfg.setdefault("sources", {})
    for url in urls:
        found = manual.detect_ats(url)
        if not found:
            console.print(f"[yellow]{url}: unknown job board. Add it as an RSS feed or paste jobs with `add`.[/yellow]")
            continue
        source, slug, _ = found
        current = sources.get(source) or []
        if slug in current:
            console.print(f"  {source}:{slug} already watched")
            continue
        sources[source] = current + [slug]
        n = company.probe(source, slug) if source != "workday" else None
        console.print(f"[green]  + {source}:{slug}[/green]" + (f" ({n} open jobs)" if n is not None else ""))
    save_config(cfg)


@companies.command(name="list")
def companies_list() -> None:
    """Show watched companies."""
    for source, items in (load_config().get("sources") or {}).items():
        for item in items or []:
            console.print(f"  {source}: {item.get('name') if isinstance(item, dict) else item}")


@click.command()
@click.option("--all", "show_all", is_flag=True, help="Include jobs already shown in an earlier digest.")
@click.option("--send", is_flag=True, help="Send it via your notify channel instead of printing.")
def digest(show_all: bool, send: bool) -> None:
    """Today's new top matches, follow-ups due, and upcoming interviews."""
    from .. import notify

    cfg = load_config()
    text, n = pipeline.digest(cfg, only_new=not show_all, mark=send)
    text = text or "Nothing new today."
    if send:
        channel = notify.send(cfg, f"Job digest: {n} new match(es)", text)
        console.print(f"[green]Sent via {channel}.[/green]")
    else:
        console.print(text)


COMMANDS = [add, keywords_cmd, companies, digest]
