"""Working one job: analyze it, prepare its folder, check edits, export the resume.

The tool gathers facts and checks honesty; the writing (resume wording, cover
letter, emails) is done by you or by Claude Code in conversation.
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import click
from rich.table import Table

from .. import db, keywords, network, pipeline, resume_io, tailor
from ..config import application_dir, company_name, console, load_config

STATUS_STYLE = {"GOOD": "green", "WORDING": "cyan", "STRENGTHEN": "yellow", "BURIED": "yellow",
                "MISSING": "red", "NICE-TO-HAVE": "dim"}


def _job_or_exit(conn, job_id: str) -> tuple[dict, str | None, float]:
    try:
        return pipeline.job_and_track(conn, job_id)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/red]")
        sys.exit(1)


def print_analysis(job: dict, a: keywords.JobAnalysis, limit: int = 30) -> None:
    console.print(f"\n[bold]{job['title']}[/bold] at {company_name(job)}")
    meta = [f"resume covers [bold]{a.coverage:.0%}[/bold] of what they require"]
    if a.salary:
        meta.append(f"${a.salary[0]:,}-${a.salary[1]:,}")
    if a.years_required:
        meta.append(f"{a.years_required}+ yrs")
    console.print("  " + "  |  ".join(meta))
    table = Table(show_lines=False)
    table.add_column("Term")
    table.add_column("Job says", justify="right")
    table.add_column("Importance")
    table.add_column("Your resume")
    table.add_column("Status")
    table.add_column("Do this", max_width=60)
    for t in a.terms[:limit]:
        where = (f"{t.resume_bullets}x in bullets" if t.resume_bullets else "") + \
                (f"{', ' if t.resume_bullets else ''}skills list" if t.resume_skills else "")
        style = STATUS_STYLE.get(t.status, "")
        table.add_row(t.term, f"{t.job_count}x", t.importance, where or "-",
                      f"[{style}]{t.status}[/{style}]", t.action)
    console.print(table)
    if a.wording:
        console.print("[cyan]Mirror their wording:[/cyan] " +
                      "; ".join(f"they say \"{j}\", you say \"{r}\"" for j, r in a.wording))
    if a.phrases:
        console.print("[dim]Phrases they repeat: " +
                      ", ".join(f"{p} ({n}x)" for p, n, _ in a.phrases[:8]) + "[/dim]")


@click.command()
@click.argument("job_id")
@click.option("--track", default=None, help="Resume track to compare (default: best match).")
@click.option("--save", is_flag=True, help="Also write analysis.md to the job's folder.")
def analyze(job_id: str, track: str | None, save: bool) -> None:
    """Read a job's requirements and show what your resume needs to say more."""
    cfg = load_config()
    with db.connect() as conn:
        job, best, _ = _job_or_exit(conn, job_id)
    _, resume_text = pipeline.resume_for(cfg, track or best)
    a = keywords.analyze_job(job, resume_text, pipeline.extra_terms(cfg))
    print_analysis(job, a)
    if save:
        path = application_dir(job, cfg) / "analysis.md"
        path.write_text(pipeline.analysis_markdown(job, a), encoding="utf-8")
        console.print(f"[green]Saved[/green] {path}")


@click.command()
@click.argument("job_id")
@click.option("--open", "open_posting", is_flag=True, help="Also open the posting in the browser.")
def prepare(job_id: str, open_posting: bool) -> None:
    """Set up a job's folder: posting, analysis, and your resume reordered for it."""
    cfg = load_config()
    try:
        out = pipeline.prepare(cfg, job_id, log=console.print)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/red]")
        sys.exit(1)
    for t in out["result"].todo[:12]:
        console.print(f"  [yellow]edit:[/yellow] {t}")
    console.print(f"Next: edit {out['resume'].name}, then `jobsearch check {job_id}`.")
    if open_posting and out["job"].get("url"):
        webbrowser.open(out["job"]["url"])


def _resume_file(cfg: dict, job: dict, job_id: str, file: str | None) -> Path:
    path = Path(file) if file else application_dir(job, cfg) / f"{pipeline._resume_stem(cfg, job)}.md"
    if not path.exists():
        console.print(f"[red]{path} not found. Run `jobsearch prepare {job_id}` first or pass a file.[/red]")
        sys.exit(1)
    return path


@click.command()
@click.argument("job_id")
@click.argument("file", required=False)
def check(job_id: str, file: str | None) -> None:
    """After editing a resume: re-score it and flag anything not in your original resume."""
    cfg = load_config()
    with db.connect() as conn:
        job, best, _ = _job_or_exit(conn, job_id)
    _, master = pipeline.resume_for(cfg, best)
    path = _resume_file(cfg, job, job_id, file)
    r = tailor.check(job, master, resume_io.read_text(path), pipeline.extra_terms(cfg))
    console.print(f"[bold]{path.name}[/bold]: coverage of required terms "
                  f"{r.coverage_before:.0%} (original) to [bold]{r.coverage_after:.0%}[/bold]")
    if r.warnings:
        console.print("[red]Not in your original resume. Remove these unless they're true:[/red]")
        for w in r.warnings:
            console.print(f"  [red]-[/red] {w}")
    else:
        console.print("[green]Nothing invented: every skill and number traces back to your resume.[/green]")
    for note in r.changes:
        console.print(f"  [cyan]reworded:[/cyan] {note}")
    for t in r.todo[:10]:
        console.print(f"  [yellow]still open:[/yellow] {t}")


@click.command()
@click.argument("job_id")
@click.argument("file", required=False)
def export(job_id: str, file: str | None) -> None:
    """Write an ATS-safe .docx from the edited resume .md."""
    cfg = load_config()
    with db.connect() as conn:
        job, _, _ = _job_or_exit(conn, job_id)
    path = _resume_file(cfg, job, job_id, file)
    out = resume_io.write_docx(resume_io.load(path), path.with_suffix(".docx"))
    with db.connect() as conn:
        conn.execute("UPDATE applications SET resume_path = ? WHERE job_id = ?", (str(out), job_id))
    console.print(f"[green]Wrote[/green] {out}")


@click.command()
@click.argument("job_id")
def contacts(job_id: str) -> None:
    """People you know at the company, plus links to find the recruiter and hiring manager."""
    with db.connect() as conn:
        job, _, _ = _job_or_exit(conn, job_id)
        refs = network.referrals(conn, company_name(job))
    comp = company_name(job)
    if refs:
        console.print(f"[bold green]You know {len(refs)} people at {comp}:[/bold green]")
        for r in refs[:10]:
            console.print(f"  {r['name']}, {r['position'] or ''}  {r['url'] or ''}")
    else:
        console.print(f"[dim]No connections at {comp} found (import yours with `jobsearch network import`).[/dim]")
    console.print("\n[bold]Find the right people:[/bold]")
    for label, url in network.people_search_links(comp, job["title"]).items():
        console.print(f"  {label}: {url}")


@click.command()
@click.argument("resume_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--show-text", is_flag=True, help="Print the text an ATS would extract.")
def ats(resume_file: str, show_text: bool) -> None:
    """Check how an applicant tracking system will read your resume file."""
    for level, msg in resume_io.ats_check(resume_file):
        color = {"bad": "red", "warn": "yellow", "ok": "green"}[level]
        console.print(f"[{color}]{level.upper():5}[/{color}] {msg}")
    if show_text:
        console.rule("Extracted text")
        console.print(resume_io.read_text(resume_file))


COMMANDS = [analyze, prepare, check, export, contacts, ats]
