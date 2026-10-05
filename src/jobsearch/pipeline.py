"""Operations shared by the CLI, the daily scheduled run, and the Telegram bot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from . import db, jd, keywords, matcher, quality, resume_io, tailor
from .config import application_dir, company_name
from .sources import ashby, greenhouse, lever, rss, smartrecruiters, workable, workday

Log = Callable[[str], None]

ADAPTERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "workable": workable.fetch,
    "smartrecruiters": smartrecruiters.fetch,
}


def passes_filters(job: dict, filters: dict) -> bool:
    title = (job.get("title") or "").lower()
    loc = (job.get("location") or "").lower()
    for term in filters.get("exclude_title_terms", []) or []:
        if term.lower() in title:
            return False
    include_titles = filters.get("include_title_terms") or []
    if include_titles and not any(t.lower() in title for t in include_titles):
        return False
    include_locs = filters.get("include_locations") or []
    if include_locs and loc:
        if not any(L.lower() in loc for L in include_locs):
            return False
    return True


def _store(conn, source: str, slug: str, jobs: list[dict], filters: dict, log: Log) -> tuple[int, int]:
    kept: set[str] = set()
    new = 0
    for j in jobs:
        if not passes_filters(j, filters):
            continue
        kept.add(j["id"])
        if not j.get("salary_min"):
            sal = jd.extract_salary(j.get("description") or "")
            if sal:
                j["salary_min"], j["salary_max"] = sal
        if db.upsert_job(conn, j):
            new += 1
    closed = db.mark_jobs_closed(conn, source, slug, kept)
    log(f"  {source}:{slug} - {len(kept)} open, {new} new, {closed} closed")
    return len(kept), new


def discover(cfg: dict, log: Log = print) -> tuple[int, int]:
    """Pull every configured source. Returns (open jobs seen, new jobs)."""
    filters = cfg.get("filters") or {}
    sources = cfg.get("sources") or {}
    search = " ".join((cfg.get("search") or {}).get("roles") or [])
    seen = new = 0
    with db.connect() as conn:
        for source, fetch in ADAPTERS.items():
            for slug in sources.get(source) or []:
                try:
                    jobs = fetch(slug)
                except Exception as e:  # noqa: BLE001
                    log(f"  [red]{source}:{slug} failed: {e}[/red]")
                    continue
                s, n = _store(conn, source, slug, jobs, filters, log)
                seen, new = seen + s, new + n
        for slug in sources.get("workday") or []:
            try:
                jobs = workday.fetch(slug, search=search)
            except Exception as e:  # noqa: BLE001
                log(f"  [red]workday:{slug} failed: {e}[/red]")
                continue
            s, n = _store(conn, "workday", slug, jobs, filters, log)
            seen, new = seen + s, new + n
        for feed in sources.get("rss") or []:
            name, url = feed.get("name"), feed.get("url")
            if not name or not url:
                continue
            try:
                jobs = rss.fetch(name, url)
            except Exception as e:  # noqa: BLE001
                log(f"  [red]rss:{name} failed: {e}[/red]")
                continue
            s, n = _store(conn, "rss", name, jobs, filters, log)
            seen, new = seen + s, new + n
        counts = quality.refresh(conn)
    log(f"  Quality pass: {counts['duplicates']} duplicates, {counts['flagged']} flagged, "
        f"{counts['with_salary']} with a posted salary")
    return seen, new


def load_tracks(cfg: dict) -> list[matcher.Track]:
    tracks = []
    for name, t in (cfg.get("resume_tracks") or {}).items():
        text = resume_io.read_text(t["path"])
        tracks.append(matcher.Track(name=name, resume_text=text,
                                    keywords=[k.lower() for k in (t.get("keywords") or [])]))
    return tracks


def match(cfg: dict, log: Log = print) -> int:
    tracks = load_tracks(cfg)
    with db.connect() as conn:
        rows = conn.execute("SELECT id, title, description FROM jobs WHERE is_open = 1").fetchall()
        jobs = [(r["id"], r["title"], r["description"]) for r in rows]
        for track in tracks:
            for job_id, score in matcher.score_jobs(track, jobs).items():
                db.record_score(conn, job_id, track.name, score)
            log(f"  Scored {len(jobs)} jobs against track [bold]{track.name}[/bold]")
    return len(jobs)


def extra_terms(cfg: dict) -> list[str]:
    terms = list((cfg.get("keywords") or {}).get("extra") or [])
    for t in (cfg.get("resume_tracks") or {}).values():
        terms += t.get("keywords") or []
    return terms


def resume_for(cfg: dict, track: str | None) -> tuple[str, str]:
    """(track name, resume text) to tailor from. Prefers the master resume if set."""
    tracks = cfg.get("resume_tracks") or {}
    if not tracks:
        raise ValueError("No resume_tracks configured. Run `jobsearch setup`.")
    name = track if track in tracks else next(iter(tracks))
    t = tracks[name]
    path = t.get("master") or cfg.get("master_resume") or t["path"]
    return name, resume_io.read_text(path)


def job_and_track(conn, job_id: str) -> tuple[dict, str | None, float]:
    job = db.get_job(conn, job_id)
    if not job:
        raise KeyError(f"No job with id {job_id}. Use `jobsearch list` to find ids.")
    best = db.best_track(conn, job_id)
    return job, (best[0] if best else None), (best[1] if best else 0.0)


def prepare(cfg: dict, job_id: str, log: Log = print) -> dict:
    """Write the facts for one application into its folder; the writing happens elsewhere.

    posting.md is the full posting, analysis.md the requirement/resume comparison,
    and <name>_Resume_<company>.md your resume reordered for this job, ready to edit.
    """
    with db.connect() as conn:
        job, track, _ = job_and_track(conn, job_id)
        track, resume_text = resume_for(cfg, track)
        terms = extra_terms(cfg)
        out_dir = application_dir(job, cfg)

        (out_dir / "posting.md").write_text(posting_markdown(job), encoding="utf-8")
        analysis = keywords.analyze_job(job, resume_text, terms)
        (out_dir / "analysis.md").write_text(analysis_markdown(job, analysis), encoding="utf-8")

        result = tailor.tailor(job, resume_text, extra_terms=terms,
                               max_bullets=int((cfg.get("tailor") or {}).get("max_bullets_per_role", 5)))
        stem = _resume_stem(cfg, job)
        resume_md = resume_io.write_markdown(result.resume, out_dir / f"{stem}.md")
        (out_dir / "tailor_notes.md").write_text(tailor_markdown(result), encoding="utf-8")
        log(f"  {out_dir}: posting.md, analysis.md, {stem}.md, tailor_notes.md")

        app = db.get_application(conn, job_id)
        db.update_application(conn, job_id, (app or {}).get("status") or "drafted",
                              followup_days=cfg.get("followup_days") or {}, resume_track=track,
                              resume_path=str(resume_md), bundle_dir=str(out_dir))
    return {"dir": out_dir, "job": job, "result": result, "analysis": analysis, "resume": resume_md}


def posting_markdown(job: dict) -> str:
    meta = [f"- Company: {company_name(job)}", f"- Location: {job.get('location') or 'n/a'}"]
    if job.get("salary_min"):
        meta.append(f"- Salary: ${job['salary_min']:,} to ${(job.get('salary_max') or job['salary_min']):,}")
    if job.get("url"):
        meta.append(f"- Link: {job['url']}")
    meta.append(f"- Tracker id: {job['id']}")
    return f"# {job.get('title')}\n\n" + "\n".join(meta) + f"\n\n---\n\n{job.get('description') or ''}\n"


def _resume_stem(cfg: dict, job: dict) -> str:
    name = ((cfg.get("user") or {}).get("name") or "Resume").replace(" ", "_")
    comp = company_name(job).replace(" ", "_")
    return f"{name}_Resume_{comp}"


def analysis_markdown(job: dict, a: keywords.JobAnalysis) -> str:
    lines = [f"# {job.get('title')} at {company_name(job)}: keyword analysis", "",
             f"- Resume coverage of required terms: **{a.coverage:.0%}**"]
    if a.salary:
        lines.append(f"- Salary: ${a.salary[0]:,} to ${a.salary[1]:,}")
    if a.years_required:
        lines.append(f"- Years asked for: {a.years_required}+")
    lines += ["", "| Term | Job says | Importance | Your bullets | Skills list | Status | Do this |",
              "|---|---|---|---|---|---|---|"]
    for t in a.terms:
        lines.append(f"| {t.term} | {t.job_count}x | {t.importance} | {t.resume_bullets} | "
                     f"{t.resume_skills} | {t.status} | {t.action} |")
    if a.wording:
        lines += ["", "## Mirror their wording", ""]
        lines += [f"- They say **{j}**, you say *{r}*" for j, r in a.wording]
    if a.phrases:
        lines += ["", "## Other phrases they repeat", ""]
        lines += [f"- {p} ({n}x){' (on your resume)' if on else ''}" for p, n, on in a.phrases]
    return "\n".join(lines) + "\n"


def tailor_markdown(r: tailor.TailorResult) -> str:
    lines = ["# Tailoring notes", "",
             f"Coverage of the job's required terms: {r.coverage_before:.0%} to {r.coverage_after:.0%}",
             ""]
    if r.warnings:
        lines += ["## Check these before sending", ""] + [f"- {w}" for w in r.warnings] + [""]
    if r.changes:
        lines += ["## What changed", ""] + [f"- {c}" for c in r.changes] + [""]
    if r.todo:
        lines += ["## Edits to make by hand", ""] + [f"- {t}" for t in r.todo]
    return "\n".join(lines) + "\n"


def digest(cfg: dict, *, only_new: bool = True, min_score: float | None = None,
           limit: int | None = None, mark: bool = True) -> tuple[str, int]:
    """Text digest of new top matches + follow-ups + interviews. Returns (text, new_count)."""
    d = cfg.get("digest") or {}
    min_score = d.get("min_score", 0.2) if min_score is None else min_score
    limit = limit or d.get("max_items", 10)
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        sql = """SELECT j.*, MAX(s.score) score FROM jobs j JOIN scores s ON s.job_id = j.id
                 WHERE j.is_open = 1 AND j.dup_of IS NULL {new} GROUP BY j.id HAVING score >= ?
                 ORDER BY score DESC LIMIT ?"""
        rows = [dict(r) for r in conn.execute(
            sql.format(new="AND j.notified_at IS NULL" if only_new else ""), (min_score, limit))]
        due = [dict(r) for r in conn.execute(
            """SELECT a.job_id, a.status, j.title, j.source_company, j.company_name FROM applications a
               JOIN jobs j ON j.id = a.job_id WHERE a.next_followup_at <= ?
               AND a.status NOT IN ('rejected','offer','withdrawn')""",
            (now.isoformat(timespec="seconds"),))]
        soon = [dict(r) for r in conn.execute(
            """SELECT i.starts_at, j.title, j.source_company, j.company_name FROM interviews i
               JOIN jobs j ON j.id = i.job_id WHERE i.starts_at BETWEEN ? AND ? ORDER BY i.starts_at""",
            (datetime.now().isoformat(timespec="minutes"),
             (datetime.now() + timedelta(days=2)).isoformat(timespec="minutes")))]
        ended = [dict(r) for r in conn.execute(
            """SELECT i.starts_at, i.interviewer, j.title, j.source_company, j.company_name FROM interviews i
               JOIN jobs j ON j.id = i.job_id WHERE i.starts_at BETWEEN ? AND ? ORDER BY i.starts_at""",
            ((datetime.now() - timedelta(days=1)).isoformat(timespec="minutes"),
             datetime.now().isoformat(timespec="minutes")))]
        if mark and rows:
            conn.executemany("UPDATE jobs SET notified_at = ? WHERE id = ?",
                             [(now.isoformat(timespec="seconds"), r["id"]) for r in rows])

    lines = []
    if rows:
        lines.append(f"{len(rows)} new match(es):")
        for r in rows:
            age = quality.age_days(r)
            bits = [f"{r['score']:.2f}", f"{r['title']} - {company_name(r)}"]
            if r.get("location"):
                bits.append(r["location"])
            if r.get("salary_min"):
                bits.append(f"${r['salary_min'] // 1000}k-${(r['salary_max'] or r['salary_min']) // 1000}k")
            if age is not None:
                bits.append(f"{age}d old")
            if r.get("flags"):
                bits.append(f"[{r['flags']}]")
            lines.append(" | ".join(bits))
            if r.get("url"):
                lines.append(f"  {r['url']}")
            lines.append(f"  id: {r['id']}")
    if soon:
        lines += ["", "Interviews in the next 48h:"]
        lines += [f"- {s['starts_at']}: {s['title']} at {company_name(s)}" for s in soon]
    if ended:
        lines += ["", "Interviews in the last day (send a thank-you):"]
        lines += [f"- {e['title']} at {company_name(e)}" + (f" with {e['interviewer']}" if e["interviewer"] else "")
                  for e in ended]
    if due:
        lines += ["", f"{len(due)} follow-up(s) due:"]
        lines += [f"- {x['title']} at {company_name(x)} ({x['status']})" for x in due]
    return "\n".join(lines).strip(), len(rows)
