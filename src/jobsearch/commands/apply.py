"""Working one job: analyze it, tailor for it, and build everything to apply."""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import click
from rich.table import Table

from .. import answers, db, keywords, letters, network, pipeline, resume_io, tailor
from ..config import ANSWERS_PATH, application_dir, company_name, console, load_config, load_yaml

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
@click.option("--save", is_flag=True, help="Also write applications/<job>/analysis.md")
def analyze(job_id: str, track: str | None, save: bool) -> None:
    """Read a job's requirements and show what your resume needs to say more."""
    cfg = load_config()
    with db.connect() as conn:
        job, best, _ = _job_or_exit(conn, job_id)
    _, resume_text = pipeline.resume_for(cfg, track or best)
    a = keywords.analyze_job(job, resume_text, pipeline.extra_terms(cfg))
    print_analysis(job, a)
    if save:
        path = application_dir(job_id) / "analysis.md"
        path.write_text(pipeline.analysis_markdown(job, a), encoding="utf-8")
        console.print(f"[green]Saved[/green] {path}")


@click.command(name="tailor")
@click.argument("job_id")
@click.option("--track", default=None)
def tailor_cmd(job_id: str, track: str | None) -> None:
    """Draft resume for one job: bullets and skills reordered, plus the edits to make."""
    cfg = load_config()
    with db.connect() as conn:
        job, best, _ = _job_or_exit(conn, job_id)
    _, resume_text = pipeline.resume_for(cfg, track or best)
    r = tailor.tailor(job, resume_text, extra_terms=pipeline.extra_terms(cfg),
                      max_bullets=int((cfg.get("tailor") or {}).get("max_bullets_per_role", 5)))
    out = application_dir(job_id)
    stem = pipeline._resume_stem(cfg, job)
    resume_io.write_markdown(r.resume, out / f"{stem}.md")
    docx_path = resume_io.write_docx(r.resume, out / f"{stem}.docx")
    (out / "tailor_notes.md").write_text(pipeline.tailor_markdown(r), encoding="utf-8")
    with db.connect() as conn:
        app = db.get_application(conn, job_id)
        db.update_application(conn, job_id, (app or {}).get("status") or "drafted",
                              followup_days=cfg.get("followup_days") or {}, resume_path=str(docx_path))
    console.print(f"[green]Draft resume:[/green] {out / (stem + '.md')}  (and .docx)")
    for t in r.todo[:12]:
        console.print(f"  [yellow]TODO:[/yellow] {t}")
    console.print(f"Edit the .md (or ask Claude Code to), then run `jobsearch check {job_id}`.")


def _bundle_resume(cfg: dict, job: dict, job_id: str, file: str | None) -> Path:
    path = Path(file) if file else application_dir(job_id) / f"{pipeline._resume_stem(cfg, job)}.md"
    if not path.exists():
        console.print(f"[red]{path} not found. Run `jobsearch tailor {job_id}` first or pass a file.[/red]")
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
    path = _bundle_resume(cfg, job, job_id, file)
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
    """Rebuild the ATS-safe .docx from the edited resume .md."""
    cfg = load_config()
    with db.connect() as conn:
        job, _, _ = _job_or_exit(conn, job_id)
    path = _bundle_resume(cfg, job, job_id, file)
    resume = resume_io.parse(_md_to_text(path.read_text(encoding="utf-8")))
    out = resume_io.write_docx(resume, path.with_suffix(".docx"))
    with db.connect() as conn:
        conn.execute("UPDATE applications SET resume_path = ? WHERE job_id = ?", (str(out), job_id))
    console.print(f"[green]Wrote[/green] {out}")


def _md_to_text(md: str) -> str:
    """Our resume markdown back to the plain layout resume_io.parse expects."""
    lines = []
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            lines += ["", s[3:].upper()]
        elif s.startswith("# "):
            lines.append(s[2:])
        elif s.startswith("**") and s.endswith("**"):
            lines.append(s.strip("*"))
        else:
            lines.append(ln)
    return "\n".join(lines)


@click.command()
@click.argument("job_id")
def letter(job_id: str) -> None:
    """Cover letter draft for one job, with [CUSTOMIZE] markers to fill in."""
    cfg = load_config()
    with db.connect() as conn:
        job, best, score = _job_or_exit(conn, job_id)
    track, resume_text = pipeline.resume_for(cfg, best)
    a = keywords.analyze_job(job, resume_text, pipeline.extra_terms(cfg))
    body = letters.cover_letter(cfg.get("user") or {}, job, resume_text, a, track, score)
    path = application_dir(job_id) / "cover_letter.md"
    path.write_text(body, encoding="utf-8")
    console.print(f"[green]Cover letter:[/green] {path}")


@click.command(name="answers")
@click.argument("job_id")
@click.option("--question", "-q", multiple=True, help="Extra form question(s) to add.")
def answers_cmd(job_id: str, question: tuple[str, ...]) -> None:
    """Fill your answer bank for one job, plus stubs for unusual form questions."""
    cfg = load_config()
    bank = load_yaml(ANSWERS_PATH)
    if not bank:
        console.print("[yellow]No answers.yaml yet. Copy answers.example.yaml to answers.yaml and fill it in.[/yellow]")
    with db.connect() as conn:
        job, best, _ = _job_or_exit(conn, job_id)
    _, resume_text = pipeline.resume_for(cfg, best)
    a = keywords.analyze_job(job, resume_text, pipeline.extra_terms(cfg))
    text = answers.render(bank, job, cfg, a) if bank else ""
    for q in question:
        text += f"\n**{q}**\n{answers.question_stub(q, resume_text, a)}\n"
    path = application_dir(job_id) / "answers.md"
    path.write_text(text, encoding="utf-8")
    console.print(text)
    console.print(f"[green]Saved[/green] {path}")


@click.command(name="apply")
@click.argument("job_id")
@click.option("--no-open", is_flag=True, help="Don't open the folder and posting.")
@click.option("--applied", "mark_applied", is_flag=True, help="Mark as applied without asking.")
def apply_cmd(job_id: str, no_open: bool, mark_applied: bool) -> None:
    """Build the application folder, open the posting, and log it once you've sent it."""
    cfg = load_config()
    console.print(f"[bold]Building application kit for {job_id}[/bold]")
    try:
        out = pipeline.build_bundle(cfg, job_id, log=console.print)
    except KeyError as e:
        console.print(f"[red]{e.args[0]}[/red]")
        sys.exit(1)
    console.print(f"\n[green]Kit ready:[/green] {out['dir']}")
    console.print("Next: finish the wording (CLAUDE_BRIEF.md has the steps), run "
                  f"`jobsearch check {job_id}`, then submit on the company's site yourself.")
    if not no_open:
        webbrowser.open(out["dir"].resolve().as_uri())
        if out["job"].get("url"):
            webbrowser.open(out["job"]["url"])
    if mark_applied or click.confirm("Did you submit the application?", default=False):
        with db.connect() as conn:
            db.update_application(conn, job_id, "applied", followup_days=cfg.get("followup_days") or {})
        days = (cfg.get("followup_days") or {}).get("applied")
        console.print("[green]Logged as applied.[/green]" + (f" Follow-up reminder in {days} days." if days else ""))
    else:
        console.print("Left as drafted. Run `jobsearch track <id> --status applied` once you submit.")


@click.command()
@click.argument("job_id")
@click.option("--name", "contact_name", default=None, help="Who you're writing to.")
def outreach(job_id: str, contact_name: str | None) -> None:
    """Referrals from your network, people-search links, and outreach drafts."""
    cfg = load_config()
    with db.connect() as conn:
        job, best, _ = _job_or_exit(conn, job_id)
        refs = network.referrals(conn, company_name(job))
    _, resume_text = pipeline.resume_for(cfg, best)
    a = keywords.analyze_job(job, resume_text, pipeline.extra_terms(cfg))
    comp = company_name(job)
    if refs:
        console.print(f"[bold green]You know {len(refs)} people at {comp}:[/bold green]")
        for r in refs[:10]:
            console.print(f"  {r['name']}, {r['position'] or ''}  {r['url'] or ''}")
        contact_name = contact_name or refs[0]["name"]
    else:
        console.print(f"[dim]No connections at {comp} found (import yours with `jobsearch network import`).[/dim]")
    console.print("\n[bold]Find the right people:[/bold]")
    for label, url in network.people_search_links(comp, job["title"]).items():
        console.print(f"  {label}: {url}")
    msgs = letters.outreach(cfg.get("user") or {}, job, a, contact_name)
    text = (f"# Outreach: {job['title']} at {comp}\n\n## LinkedIn note\n{msgs['linkedin']}\n\n"
            f"## Email\nSubject: {msgs['email_subject']}\n\n{msgs['email_body']}\n")
    path = application_dir(job_id) / "outreach.md"
    path.write_text(text, encoding="utf-8")
    console.print(f"\n{text}\n[green]Saved[/green] {path}")


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


COMMANDS = [analyze, tailor_cmd, check, export, letter, answers_cmd, apply_cmd, outreach, ats]
