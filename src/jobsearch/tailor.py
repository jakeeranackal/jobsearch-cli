"""Tailor a master resume to one job, and check edited resumes for honesty.

tailor(): reorder bullets inside each role and the skills list by what the job
weighs most, trim each role to its strongest bullets, and list the edits still
worth making. The actual rewording is done by you (or Claude Code) using that
list; this module never calls an AI service.

check(): after a resume has been edited, recompute coverage and flag any skill
or number that isn't in the master resume, because a made-up claim costs more
in the interview than it gains on the screen.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from . import keywords, resume_io
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
    """Skills or numbers in the tailored resume that the master never mentions.

    Rewordings the analysis itself suggests ("reports" to "dashboards") are not
    flagged here; rewordings() lists them so they still get a second look.
    """
    warnings = []
    reworded = {name for name, _ in rewordings(master_text, tailored_text, extra_terms)}
    for skill in keywords.all_skills(extra_terms):
        if skill.name in reworded:
            continue
        if skill.count(tailored_text) and not skill.count(master_text):
            warnings.append(f"'{skill.name}' appears but isn't in your master resume. "
                            f"Remove it unless it's true.")
    master_nums = set(_NUM.findall(master_text))
    for n in sorted(set(_NUM.findall(tailored_text)) - master_nums):
        if len(n.strip("$%,.")) > 1 or "%" in n or "$" in n:
            warnings.append(f"Number '{n}' isn't in your master resume. Check it's accurate.")
    return warnings


def rewordings(master_text: str, tailored_text: str,
               extra_terms: list[str] | None = None) -> list[tuple[str, str]]:
    """(new skill, original word) pairs where a new term swaps in for a near-synonym."""
    _, groups = keywords.load_lexicon()
    master_l = master_text.lower()
    out = []
    for skill in keywords.all_skills(extra_terms):
        if not skill.count(tailored_text) or skill.count(master_text):
            continue
        forms = {a.lower() for a in skill.aliases} | {skill.name.lower()}
        for group in groups:
            if not any(w in forms or w.rstrip("s") in forms for w in group):
                continue
            original = next((w for w in group if w not in forms
                             and re.search(rf"\b{re.escape(w)}\b", master_l)), None)
            if original:
                out.append((skill.name, original))
                break
    return out


def tailor(job: dict, master_text: str, *, extra_terms: list[str] | None = None,
           max_bullets: int = 5) -> TailorResult:
    analysis = keywords.analyze_job(job, master_text, extra_terms)
    tailored = copy.deepcopy(resume_io.parse(master_text))
    changes = list(dict.fromkeys(_reorder(tailored, analysis, max_bullets)))
    after = keywords.analyze_job(job, tailored.to_text(), extra_terms)
    return TailorResult(
        resume=tailored,
        coverage_before=analysis.coverage,
        coverage_after=after.coverage,
        changes=changes,
        todo=_todo(analysis),
    )


def check(job: dict, master_text: str, edited_text: str,
          extra_terms: list[str] | None = None) -> TailorResult:
    """Score an edited resume against the job and the master resume."""
    before = keywords.analyze_job(job, master_text, extra_terms)
    after = keywords.analyze_job(job, edited_text, extra_terms)
    return TailorResult(
        resume=resume_io.parse(edited_text),
        coverage_before=before.coverage,
        coverage_after=after.coverage,
        changes=[f"'{new}' replaces '{old}'. Fine if accurate."
                 for new, old in rewordings(master_text, edited_text, extra_terms)],
        todo=_todo(after),
        warnings=fabrication_check(master_text, edited_text, extra_terms),
    )
