"""Tailor a master resume to one job.

Without Claude: reorder bullets inside each role and the skills list by what
the job weighs most, trim each role to its strongest bullets, and list the
edits you should make by hand.

With Claude: rewrite bullets in the job's wording, from the master resume's
facts only. A fabrication check then flags any skill or number in the output
that isn't in the master resume, because a made-up claim costs more in the
interview than it gains on the screen.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from . import keywords, llm, resume_io
from .resume_io import Item, Resume, Section

_NUM = re.compile(r"\d[\d,.]*%?|\$\d[\d,.]*[kKmM]?")


@dataclass
class TailorResult:
    resume: Resume
    coverage_before: float
    coverage_after: float
    changes: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_ai: bool = False


def _term_weights(analysis: keywords.JobAnalysis) -> list[tuple[keywords.Skill, float]]:
    by_name = {s.name: s for s in keywords.all_skills([t.term for t in analysis.terms])}
    return [(by_name[t.term], t.weight) for t in analysis.terms if t.term in by_name]


def _relevance(text: str, weights) -> float:
    return sum(w * min(skill.count(text), 2) for skill, w in weights)


def _reorder(resume: Resume, analysis: keywords.JobAnalysis, max_bullets: int) -> list[str]:
    weights = _term_weights(analysis)
    changes: list[str] = []
    for sec in resume.sections:
        if sec.key == "skills":
            _reorder_skills(sec, weights, changes)
            continue
        new_items: list[Item] = []
        group: list[Item] = []
        for item in sec.items + [Item("end", "")]:
            if item.kind == "bullet":
                group.append(item)
                continue
            if group:
                label = _last_heading(new_items) or sec.title
                new_items.extend(_rank_bullets(group, weights, max_bullets, label, changes))
                group = []
            if item.kind != "end":
                new_items.append(item)
        sec.items = new_items
    return changes


def _rank_bullets(group: list[Item], weights, max_bullets: int, label: str,
                  changes: list[str]) -> list[Item]:
    ranked = sorted(group, key=lambda i: _relevance(i.text, weights), reverse=True)
    if ranked != group:
        changes.append(f"Reordered bullets under '{label}'")
    if max_bullets and len(ranked) > max_bullets:
        changes.append(f"Trimmed {len(ranked) - max_bullets} weak bullet(s) under '{label}'")
        ranked = ranked[:max_bullets]
    return ranked


def _last_heading(items: list[Item]) -> str | None:
    return next((i.text for i in reversed(items) if i.kind == "heading"), None)


def _reorder_skills(sec: Section, weights, changes: list[str]) -> None:
    for item in sec.items:
        label, sep, rest = item.text.partition(":")
        body = rest if sep and len(label) < 30 else item.text
        parts = [p.strip() for p in re.split(r"[,;|•]", body) if p.strip()]
        if len(parts) < 3:
            continue
        ranked = sorted(parts, key=lambda p: _relevance(p, weights), reverse=True)
        if ranked != parts:
            joined = ", ".join(ranked)
            item.text = f"{label}: {joined}" if sep and len(label) < 30 else joined
            changes.append("Moved the job's top skills to the front of your skills list")


def _todo(analysis: keywords.JobAnalysis) -> list[str]:
    out = []
    for t in analysis.terms:
        if t.status in ("BURIED", "STRENGTHEN", "WORDING") or (
            t.status == "MISSING" and t.importance == "required"
        ):
            out.append(f"{t.term} [{t.status}]: {t.action}")
    covered = {t.job_form for t in analysis.terms if t.status == "WORDING"}
    for job_word, yours in analysis.wording:
        if job_word not in covered:
            out.append(f"Wording: they say \"{job_word}\", you say \"{yours}\"")
    return out


def fabrication_check(master_text: str, tailored_text: str,
                      extra_terms: list[str] | None = None) -> list[str]:
    """Skills or numbers in the tailored resume that the master never mentions."""
    warnings = []
    for skill in keywords.all_skills(extra_terms):
        if skill.count(tailored_text) and not skill.count(master_text):
            warnings.append(f"'{skill.name}' appears but isn't in your master resume. "
                            f"Remove it unless it's true.")
    master_nums = set(_NUM.findall(master_text))
    for n in sorted(set(_NUM.findall(tailored_text)) - master_nums):
        if len(n.strip("$%,.")) > 1 or "%" in n or "$" in n:
            warnings.append(f"Number '{n}' isn't in your master resume. Check it's accurate.")
    return warnings


_SYSTEM = """You tailor resumes for specific job postings.

Hard rules:
- Use only facts present in the master resume. Never invent employers, titles, dates,
  tools, metrics, degrees, or responsibilities. If the job wants something the master
  resume doesn't show, leave it out and list it in "gaps".
- You may reword, reorder, merge, or drop bullets, and mirror the posting's wording
  for things the candidate actually did (e.g. "reports" -> "dashboards" only if they
  were dashboards).
- Keep every role, school, and date from the master resume. Keep 3-6 bullets per role,
  strongest and most relevant first. Start bullets with a strong verb; keep results
  and numbers that exist in the master.
- The summary is 2-3 lines aimed at this role.
- Plain text only, no markdown, no emojis."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["heading", "bullet", "text"]},
                                "text": {"type": "string"},
                            },
                            "required": ["kind", "text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "items"],
                "additionalProperties": False,
            },
        },
        "changes": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sections", "changes", "gaps"],
    "additionalProperties": False,
}


def _analysis_table(analysis: keywords.JobAnalysis) -> str:
    rows = [f"- {t.term}: job mentions {t.job_count}x ({t.importance}); "
            f"resume bullets {t.resume_bullets}, skills list {t.resume_skills}; {t.status}"
            for t in analysis.terms[:25]]
    rows += [f"- wording: job says '{j}', resume says '{r}'" for j, r in analysis.wording]
    return "\n".join(rows)


def _ai_rewrite(cfg: dict, job: dict, master: Resume, analysis: keywords.JobAnalysis) -> tuple[Resume, list[str], list[str]]:
    prompt = (
        f"JOB: {job.get('title')} at {job.get('company_name') or job.get('source_company')}\n\n"
        f"POSTING:\n{job.get('description', '')[:12000]}\n\n"
        f"KEYWORD ANALYSIS (what they weigh vs. what the resume shows):\n{_analysis_table(analysis)}\n\n"
        f"MASTER RESUME (the only source of facts):\n{master.to_text()}\n\n"
        "Return the tailored resume sections (not the name/contact header), a short list "
        "of what you changed, and the requirements you could not support from the master resume."
    )
    data = llm.ask_json(cfg, _SYSTEM, prompt, _SCHEMA, effort="high")
    out = Resume(header=list(master.header))
    for s in data["sections"]:
        out.sections.append(Section(
            title=s["title"],
            items=[Item(i["kind"], i["text"].strip()) for i in s["items"] if i["text"].strip()],
        ))
    return out, data.get("changes") or [], data.get("gaps") or []


def tailor(job: dict, master_text: str, cfg: dict | None = None, *,
           extra_terms: list[str] | None = None, use_ai: bool = True,
           max_bullets: int = 5) -> TailorResult:
    analysis = keywords.analyze_job(job, master_text, extra_terms)
    master = resume_io.parse(master_text)

    if use_ai and llm.available(cfg):
        tailored, changes, gaps = _ai_rewrite(cfg or {}, job, master, analysis)
        todo = [f"Not supported by your resume: {g}" for g in gaps]
        used_ai = True
    else:
        tailored = copy.deepcopy(master)
        changes = list(dict.fromkeys(_reorder(tailored, analysis, max_bullets)))
        todo = _todo(analysis)
        used_ai = False

    tailored_text = tailored.to_text()
    after = keywords.analyze_job(job, tailored_text, extra_terms)
    return TailorResult(
        resume=tailored,
        coverage_before=analysis.coverage,
        coverage_after=after.coverage,
        changes=changes,
        todo=todo,
        warnings=fabrication_check(master_text, tailored_text, extra_terms) if used_ai else [],
        used_ai=used_ai,
    )
