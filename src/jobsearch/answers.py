"""Application-form answer bank, filled in per job."""
from __future__ import annotations

from . import keywords, letters
from .config import company_name

_LABELS = {
    "work_authorization": "Are you authorized to work in the US?",
    "require_sponsorship": "Will you now or in the future require sponsorship?",
    "salary_expectation": "Salary expectations",
    "start_date": "When can you start?",
    "willing_to_relocate": "Willing to relocate?",
    "remote_preference": "Remote / hybrid / on-site preference",
    "how_did_you_hear": "How did you hear about us?",
    "why_this_company": "Why do you want to work here?",
    "why_this_role": "Why are you interested in this role?",
    "greatest_strength": "What's your greatest strength?",
}

# Starting points for "auto" answers; [ADD] marks what only you can write.
_AUTO = {
    "why_this_company": "[ADD: one specific thing about {company} (product, mission, recent news) "
                        "and why it matters to you]",
    "why_this_role": "The {title} role centers on {top_terms}, which is the work I've been doing "
                     "and want to go deeper on. [ADD: one concrete example]",
    "greatest_strength": "[ADD: a strength the posting values ({top_terms}), with a one-line example]",
}


class _Keep(dict):
    """format_map dict that leaves unknown {placeholders} alone."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _salary_range(job: dict, cfg: dict, posted: tuple[int, int] | None = None) -> str:
    lo, hi = (job.get("salary_min"), job.get("salary_max")) if job.get("salary_min") else (posted or (None, None))
    if lo and hi:
        return f"${lo:,}-${hi:,} (the posted range)"
    floor = (cfg.get("search") or {}).get("salary_floor")
    return f"${floor:,}+" if floor else "[ADD: your range]"


def question_stub(question: str, resume_text: str, analysis: keywords.JobAnalysis) -> str:
    """Placeholder for an unusual form question, with the resume bullets most likely to answer it."""
    options = "\n".join(f"  - {b}" for b in letters.top_bullets(resume_text, analysis, 3))
    return f"[ADD: answer to '{question}'. Strongest material from your resume:\n{options}]"


def render(bank: dict, job: dict, cfg: dict, analysis: keywords.JobAnalysis) -> str:
    fill = _Keep({
        "company": company_name(job),
        "title": job.get("title", ""),
        "salary_range": _salary_range(job, cfg, analysis.salary),
        "top_terms": ", ".join(t.term for t in analysis.top_requirements[:3]) or "this area",
    })
    lines = [f"# Application answers: {fill['title']} at {fill['company']}", ""]
    for key, label in _LABELS.items():
        value = bank.get(key)
        if value is None:
            continue
        template = _AUTO.get(key, "[ADD]") if value == "auto" else str(value)
        lines += [f"**{label}**", template.format_map(fill), ""]
    links = {k: v for k, v in (bank.get("links") or {}).items() if v}
    if links:
        lines += ["**Links**"] + [f"- {k}: {v}" for k, v in links.items()] + [""]
    eeo = bank.get("eeo") or {}
    if eeo:
        lines += ["**Voluntary self-identification**"] + [f"- {k}: {v}" for k, v in eeo.items()]
    return "\n".join(lines).strip() + "\n"
