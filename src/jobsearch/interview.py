"""Interview prep: prep sheets, a STAR story bank, salary scripts."""
from __future__ import annotations

from . import keywords, resume_io
from .config import company_name

BEHAVIORAL = [
    "Tell me about yourself.",
    "Why this role, and why us?",
    "Tell me about a time you dealt with a difficult stakeholder or client.",
    "Tell me about a time you made a mistake. What happened next?",
    "Tell me about a project you're proud of. What was your part?",
    "Describe a time you had to learn something quickly.",
    "Tell me about a time you had competing deadlines.",
    "Where do you want to be in a few years?",
]


def story_matches(stories: list[dict], analysis: keywords.JobAnalysis, limit: int = 6) -> list[tuple[dict, list[str]]]:
    """Rank stories by how many of the job's weighted terms their tags/text cover."""
    skills = keywords.all_skills([t.term for t in analysis.terms])
    by_name = {s.name: s for s in skills}
    scored = []
    for story in stories:
        text = " ".join(str(story.get(k, "")) for k in ("title", "situation", "task", "action", "result"))
        text += " " + " ".join(story.get("tags") or [])
        hits = [t for t in analysis.terms if t.term in by_name and by_name[t.term].count(text)]
        scored.append((sum(t.weight for t in hits), story, [t.term for t in hits]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(s, terms) for score, s, terms in scored[:limit] if score > 0]


def _evidence(resume_text: str, term: str) -> str:
    skill = next((s for s in keywords.all_skills([term]) if s.name == term), None)
    if not skill:
        return ""
    for b in resume_io.parse(resume_text).bullets():
        if skill.count(b):
            return b
    return ""


def prep_sheet(job: dict, resume_text: str, analysis: keywords.JobAnalysis,
               stories: list[dict], brief: str | None = None) -> str:
    company = company_name(job)
    lines = [f"# Interview prep: {job.get('title')} at {company}", ""]
    if analysis.salary:
        lines.append(f"- Posted pay: ${analysis.salary[0]:,} to ${analysis.salary[1]:,}")
    if analysis.years_required:
        lines.append(f"- Asks for {analysis.years_required}+ years")
    if job.get("url"):
        lines.append(f"- Posting: {job['url']}")
    lines += ["", "## What they'll probe, and your proof", ""]
    for t in analysis.top_requirements:
        ev = _evidence(resume_text, t.term)
        lines.append(f"- **{t.term}** ({t.job_count}x, {t.importance}): "
                     + (f"\"{ev}\"" if ev else "_no bullet yet. Prepare an example or an honest learning plan._"))
    lines += ["", "## Your stories for this job", ""]
    matched = story_matches(stories, analysis)
    if matched:
        for story, terms in matched:
            lines += [f"### {story.get('title')}  _(covers: {', '.join(terms)})_",
                      f"- Situation: {story.get('situation', '')}",
                      f"- Task: {story.get('task', '')}",
                      f"- Action: {story.get('action', '')}",
                      f"- Result: {story.get('result', '')}", ""]
    else:
        lines += ["No matching stories yet. Add some to stories.yaml (see stories.example.yaml).", ""]

    lines += ["## Likely questions", ""]
    lines += [f"- {q}" for q in BEHAVIORAL]
    lines += [f"- Walk me through how you've used {t.term}. What was the result?"
              for t in analysis.top_requirements[:5]]
    lines += ["", "## Questions to ask them", "",
              "- What does success look like in the first 90 days?",
              "- What's the biggest challenge the team is facing right now?",
              "- How does this role work with the rest of the team day to day?",
              "- What do the best people in this role do differently?",
              "- What are the next steps in the process?",
              "", "_Tip: ask Claude Code to run a mock interview from this sheet._"]
    if brief:
        lines += ["", "---", "", brief]
    return "\n".join(lines) + "\n"


def salary_help(job: dict, analysis: keywords.JobAnalysis) -> str:
    company = company_name(job)
    lines = [f"# Salary: {job.get('title')} at {company}", ""]
    if analysis.salary:
        lo, hi = analysis.salary
        lines.append(f"Posted range: **${lo:,} to ${hi:,}**. Aim for the upper half; "
                     f"anchor around ${int(lo + (hi - lo) * 0.75):,}.")
    else:
        lines.append("No posted range. Check levels.fyi, Glassdoor, and the BLS for this title and city.")
    lines += ["", "## Scripts", "",
              "**When asked for expectations early:** \"I'm focused on finding the right fit. "
              "Could you share the budgeted range for the role?\"",
              "",
              "**When you have an offer:** \"Thank you, I'm excited about this. Based on the scope "
              "and what I'm seeing for similar roles, I was hoping for closer to $[TARGET]. Is there "
              "flexibility on the base?\"",
              "",
              "**If base is fixed:** ask about a sign-on bonus, an earlier review, extra PTO, "
              "remote days, or a learning budget.",
              "",
              "Always get the final offer in writing before accepting."]
    return "\n".join(lines) + "\n"
