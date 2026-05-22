"""Cover letter drafting.

Renders a Jinja2 template per job. The output is intentionally a *draft* with
explicit `[CUSTOMIZE THIS PARAGRAPH]` markers — the tool never claims a
cover letter is ready to send.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render(*, user: dict, job: dict, resume_track: str, score: float,
           matched_keywords: list[str], resume_highlights: list[str]) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tmpl = env.get_template("cover_letter.j2")
    return tmpl.render(
        user=user,
        company=job["source_company"].replace("-", " ").title(),
        job_title=job["title"],
        job_location=job.get("location") or "",
        job_url=job["url"],
        today=date.today().strftime("%B %d, %Y"),
        resume_track=resume_track,
        score=f"{score:.3f}",
        matched_keywords=matched_keywords,
        resume_highlights=resume_highlights,
    )


def save(out_dir: Path, job_id: str, body: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Make job_id filename-safe
    safe = job_id.replace(":", "_").replace("/", "_")
    path = out_dir / f"{safe}.md"
    path.write_text(body, encoding="utf-8")
    return path


def extract_highlights(resume_text: str, max_lines: int = 6) -> list[str]:
    """Pull bullet-style lines from the resume as highlights to surface."""
    lines = []
    for raw in resume_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith(("-", "*", "•")):
            lines.append(s.lstrip("-*• ").strip())
        if len(lines) >= max_lines:
            break
    return lines or ["[Add 3-5 bullet highlights from your resume here.]"]
