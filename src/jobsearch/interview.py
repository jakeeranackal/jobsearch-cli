"""Interview prep: prep sheets, a STAR story bank, mock interviews, salary scripts."""
from __future__ import annotations

from . import keywords, llm, resume_io
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


def prep_sheet(cfg: dict, job: dict, resume_text: str, analysis: keywords.JobAnalysis,
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
    if llm.available(cfg):
        prompt = (
            f"Role: {job.get('title')} at {company}\n\nPOSTING:\n{(job.get('description') or '')[:8000]}\n\n"
            f"CANDIDATE RESUME:\n{resume_text}\n\n"
            "List the 12 questions this candidate is most likely to get, mixing behavioral, "
            "technical (on the posting's tools), and role-specific ones. For each: the question, "
            "what the interviewer is really testing, and which resume item to answer with. "
            "Then 5 sharp questions the candidate should ask them. Markdown, concise."
        )
        lines.append(llm.ask_text(cfg, "You are an experienced hiring manager and interview coach.",
                                  prompt, effort="medium"))
    else:
        lines += [f"- {q}" for q in BEHAVIORAL]
        lines += [f"- Walk me through how you've used {t.term}. What was the result?"
                  for t in analysis.top_requirements[:5]]
        lines += ["", "## Questions to ask them", "",
                  "- What does success look like in the first 90 days?",
                  "- What's the biggest challenge the team is facing right now?",
                  "- How does this role work with the rest of the team day to day?",
                  "- What do the best people in this role do differently?",
                  "- What are the next steps in the process?"]
    if brief:
        lines += ["", "---", "", brief]
    return "\n".join(lines) + "\n"


def mock_question(cfg: dict, job: dict, resume_text: str, asked: list[str]) -> str:
    prompt = (
        f"You're interviewing a candidate for {job.get('title')} at {company_name(job)}.\n"
        f"POSTING:\n{(job.get('description') or '')[:6000]}\n\nRESUME:\n{resume_text}\n\n"
        f"Already asked: {asked or 'nothing yet'}\n"
        "Ask the next single interview question. Vary between behavioral and technical. "
        "Output only the question."
    )
    return llm.ask_text(cfg, "You are a realistic, fair hiring manager.", prompt, effort="low")


def mock_feedback(cfg: dict, job: dict, question: str, answer: str) -> str:
    prompt = (
        f"Role: {job.get('title')} at {company_name(job)}\nQuestion: {question}\n"
        f"Candidate's answer: {answer}\n\n"
        "Grade 1-5. Then: what worked, what was missing (structure, specifics, result, "
        "relevance to the role), and a tighter 3-4 sentence version of their answer that uses "
        "only facts they gave. Be direct and brief."
    )
    return llm.ask_text(cfg, "You are a blunt but kind interview coach.", prompt, effort="low")


def salary_help(cfg: dict, job: dict, analysis: keywords.JobAnalysis, location: str = "") -> str:
    company = company_name(job)
    lines = [f"# Salary: {job.get('title')} at {company}", ""]
    if analysis.salary:
        lo, hi = analysis.salary
        lines.append(f"Posted range: **${lo:,} to ${hi:,}**. Aim for the upper half; "
                     f"anchor around ${int(lo + (hi - lo) * 0.75):,}.")
    else:
        lines.append("No posted range. Check levels.fyi, Glassdoor, and the BLS for this title and city.")
    if llm.available(cfg):
        prompt = (f"Role: {job.get('title')} at {company}, location {job.get('location') or location}. "
                  f"Posted range: {analysis.salary or 'none'}. Give a rough market base-salary range "
                  "from general knowledge, clearly labeled as an estimate to verify, and list "
                  "non-salary levers to negotiate. Short markdown.")
        lines += ["", llm.ask_text(cfg, "You are a compensation advisor.", prompt, effort="low")]
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
