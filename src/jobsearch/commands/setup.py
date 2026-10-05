"""`jobsearch setup`: guided first run. A new user goes from nothing to first results."""
from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path

import click

from .. import company, db, google_api, keywords, pipeline, resume_io
from ..config import (ANSWERS_PATH, CONFIG_PATH, RESUMES_DIR, SECRETS_DIR, STORIES_PATH,
                      console, save_config, try_load_config)
from ..sources import manual

DEFAULT_EXCLUDE = ["senior", "sr.", "principal", "staff", "director", "vp", "head of", "lead", "manager"]
DEFAULT_FOLLOWUP = {"applied": 7, "interviewing": 5, "drafted": 3}


def _list(prompt: str, default: list[str] | None = None) -> list[str]:
    raw = click.prompt(prompt, default=", ".join(default or []), show_default=bool(default))
    return [x.strip() for x in raw.split(",") if x.strip()]


def _step(n: int, title: str) -> None:
    console.print(f"\n[bold cyan]{n}. {title}[/bold cyan]")


def _resume_track() -> tuple[str, dict]:
    path = Path(click.prompt("  Path to your resume (.docx, .pdf or .txt)", type=click.Path(exists=True, dir_okay=False)))
    RESUMES_DIR.mkdir(exist_ok=True)
    dest = RESUMES_DIR / path.name
    if path.resolve() != dest.resolve():
        shutil.copy(path, dest)
    text = resume_io.read_text(dest)
    findings = [f for f in resume_io.ats_check(dest) if f[0] != "ok"]
    for level, msg in findings[:4]:
        console.print(f"  [{'red' if level == 'bad' else 'yellow'}]{level}:[/] {msg}")

    found = Counter()
    for skill in keywords.all_skills():
        n = skill.count(text)
        if n and skill.category != "soft skills":
            found[skill.name.lower()] = n
    suggested = [k for k, _ in found.most_common(10)]
    name = click.prompt("  Short name for this resume (e.g. data, ops)", default="main")
    kws = _list("  Keywords that should boost matches (comma separated)", suggested)
    track = {"path": str(dest).replace("\\", "/"), "keywords": kws}
    if click.confirm("  Do you also keep a longer 'master' resume with every bullet you've written?", default=False):
        master = Path(click.prompt("  Path to the master resume", type=click.Path(exists=True, dir_okay=False)))
        mdest = RESUMES_DIR / master.name
        if master.resolve() != mdest.resolve():
            shutil.copy(master, mdest)
        track["master"] = str(mdest).replace("\\", "/")
    return name, track


@click.command()
def setup() -> None:
    """Guided setup: profile, resume, target roles, companies, notifications."""
    cfg = try_load_config()
    console.print("[bold]Welcome to jobsearch.[/bold] About 5 minutes. Everything stays on this computer;")
    console.print("config.yaml, resumes, and the database are gitignored. Press Enter to accept [defaults].")

    _step(1, "About you")
    u = cfg.get("user") or {}
    user = {
        "name": click.prompt("  Full name", default=u.get("name") or None),
        "email": click.prompt("  Email", default=u.get("email") or None),
        "phone": click.prompt("  Phone", default=u.get("phone") or "", show_default=False),
        "location": click.prompt("  City, State", default=u.get("location") or "", show_default=False),
        "linkedin": click.prompt("  LinkedIn URL", default=u.get("linkedin") or "", show_default=False),
        "github": click.prompt("  GitHub/portfolio URL", default=u.get("github") or "", show_default=False),
        "timezone": u.get("timezone") or "America/New_York",
    }

    _step(2, "Your resume(s)")
    tracks = dict(cfg.get("resume_tracks") or {})
    if tracks and click.confirm(f"  Keep your existing resumes ({', '.join(tracks)})?", default=True):
        pass
    else:
        tracks = {}
        while True:
            name, track = _resume_track()
            tracks[name] = track
            if not click.confirm("  Add another resume for a different kind of role?", default=False):
                break

    _step(3, "What you're looking for")
    s = cfg.get("search") or {}
    f = cfg.get("filters") or {}
    roles = _list("  Target job titles (comma separated)", s.get("roles") or ["data analyst"])
    strict = click.confirm("  Only show jobs whose title contains one of those words?", default=False)
    exclude = _list("  Skip titles containing", f.get("exclude_title_terms") or DEFAULT_EXCLUDE)
    locations = _list("  Locations to include (blank = anywhere)", f.get("include_locations") or ["remote"])
    floor = click.prompt("  Lowest salary you'd consider (0 = no filter)", default=s.get("salary_floor") or 0, type=int)
    target = click.prompt("  Applications per week you're aiming for", default=s.get("weekly_target") or 10, type=int)

    _step(4, "Companies to watch")
    console.print("  Paste careers-page links one at a time (Greenhouse, Lever, Ashby, Workday,")
    console.print("  Workable, SmartRecruiters). Blank line when done.")
    sources = cfg.get("sources") or {"greenhouse": [], "lever": [], "ashby": [], "workday": [],
                                     "workable": [], "smartrecruiters": [], "rss": []}
    while True:
        url = click.prompt("  Careers URL", default="", show_default=False).strip()
        if not url:
            break
        found = manual.detect_ats(url)
        if not found:
            console.print("  [yellow]Unknown board. You can paste individual jobs later with `jobsearch add --paste`.[/yellow]")
            continue
        source, slug, _ = found
        if slug not in (sources.get(source) or []):
            sources[source] = (sources.get(source) or []) + [slug]
        n = company.probe(source, slug) if source != "workday" else None
        console.print(f"  [green]+ {source}:{slug}[/green]" + (f" ({n} open jobs)" if n is not None else ""))

    new_cfg = {
        **cfg,
        "user": user,
        "resume_tracks": tracks,
        "search": {**s, "roles": roles, "salary_floor": floor or None, "weekly_target": target},
        "filters": {**f, "exclude_title_terms": exclude, "include_locations": locations,
                    "include_title_terms": roles if strict else []},
        "sources": sources,
        "followup_days": cfg.get("followup_days") or DEFAULT_FOLLOWUP,
        "tailor": cfg.get("tailor") or {"max_bullets_per_role": 5},
        "digest": cfg.get("digest") or {"min_score": 0.2, "max_items": 10, "weekly_report_day": "monday"},
        "alerts": cfg.get("alerts") or {"min_score": 0.35},
        "email": cfg.get("email") or {"draft_followups": True, "auto_send_followups": False},
    }

    _step(5, "Where should daily updates go?")
    channel = click.prompt("  Channel", type=click.Choice(["none", "telegram", "gmail", "smtp"]),
                           default=(cfg.get("notify") or {}).get("channel") or "none")
    notify_cfg: dict = {"channel": channel}
    if channel in ("gmail", "smtp"):
        notify_cfg["email_to"] = click.prompt("  Send updates to", default=user["email"])
    if channel == "smtp":
        notify_cfg["smtp"] = {"host": click.prompt("  SMTP host", default="smtp.gmail.com"),
                              "port": click.prompt("  SMTP port", default=587, type=int),
                              "user": click.prompt("  SMTP username", default=user["email"]),
                              "password_env": "JOBSEARCH_SMTP_PASSWORD"}
        console.print("  Put the password (a Gmail app password works) in the JOBSEARCH_SMTP_PASSWORD env var.")
    if channel == "telegram":
        new_cfg["telegram"] = {"bot_token_env": "TELEGRAM_BOT_TOKEN",
                               "chat_id": (cfg.get("telegram") or {}).get("chat_id") or ""}
        console.print("  Run `jobsearch bot --help` for the 2-minute Telegram setup.")
    new_cfg["notify"] = notify_cfg

    if channel == "gmail" or click.confirm("  Connect Gmail so replies update statuses automatically?", default=False):
        if (SECRETS_DIR / "google_credentials.json").exists():
            try:
                console.print(f"  [green]Connected as {google_api.connect()}[/green]")
            except Exception as e:  # noqa: BLE001
                console.print(f"  [yellow]Gmail not connected: {e}[/yellow]")
        else:
            console.print("  Follow `jobsearch email connect --help` (one-time Google setup), then run it.")

    save_config(new_cfg)
    for example, target_path in (("answers.example.yaml", ANSWERS_PATH), ("stories.example.yaml", STORIES_PATH)):
        if Path(example).exists() and not target_path.exists():
            shutil.copy(example, target_path)
    db.init_db()
    Path("applications").mkdir(exist_ok=True)
    console.print(f"\n[green]Saved {CONFIG_PATH}.[/green] Also created answers.yaml and stories.yaml; fill them in when you can.")

    if any(sources.get(k) for k in sources) and click.confirm("\nPull jobs now?", default=True):
        pipeline.discover(new_cfg, log=console.print)
        pipeline.match(new_cfg, log=console.print)
        console.print("\nNext: [bold]jobsearch list[/bold], then [bold]jobsearch analyze <id>[/bold] "
                      "and [bold]jobsearch apply <id>[/bold].")
    else:
        console.print("\nNext: add companies with `jobsearch companies add <url>`, then `jobsearch discover`.")


COMMANDS = [setup]
