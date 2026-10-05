"""Drafts of everything you send: cover letters, outreach, follow-ups, thank-yous.

These are starting points filled from your resume and the job analysis, with
[ADD: ...] markers where only you know the answer. Polish them yourself or ask
Claude Code to. Nothing here sends anything.
"""
from __future__ import annotations

from . import drafter, keywords, resume_io
from .config import company_name


def top_bullets(resume_text: str, analysis: keywords.JobAnalysis, n: int = 4) -> list[str]:
    """Resume bullets that hit the most heavily weighted job terms."""
    weights = {t.term: t.weight for t in analysis.terms}
    skills = keywords.all_skills(list(weights))
    scored = []
    for b in resume_io.parse(resume_text).bullets():
        score = sum(weights.get(s.name, 0) for s in skills if s.count(b))
        scored.append((score, b))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [b for _, b in scored[:n]] or drafter.extract_highlights(resume_text, n)


def cover_letter(user: dict, job: dict, resume_text: str, analysis: keywords.JobAnalysis,
                 track: str = "", score: float = 0.0) -> str:
    matched = [t.term for t in analysis.top_requirements if t.resume_total][:4]
    return drafter.render(
        user=user, job={**job, "source_company": company_name(job)}, resume_track=track,
        score=score, matched_keywords=matched, resume_highlights=top_bullets(resume_text, analysis),
    )


def outreach(user: dict, job: dict, analysis: keywords.JobAnalysis,
             contact_name: str | None = None) -> dict[str, str]:
    """Return {'linkedin': <=300 char note, 'email_subject': ..., 'email_body': ...}."""
    company = company_name(job)
    first = (contact_name or "").split(" ")[0] or "there"
    skills = " and ".join([t.term for t in analysis.top_requirements if t.resume_total][:2])
    note = (f"Hi {first}, I just applied for the {job.get('title')} role at {company}"
            + (f". I've been doing a lot of {skills} work" if skills else "")
            + ". Would you be open to connecting?")
    body = (
        f"Hi {first},\n\n"
        f"I applied for the {job.get('title')} role at {company} and wanted to reach out directly. "
        + (f"I've been working with {skills}, which lines up with what the team is looking for.\n\n"
           if skills else "\n\n")
        + "[ADD: one sentence with your strongest result from the resume]\n\n"
        "Would you have 15 minutes in the next week or two? Happy to work around your schedule.\n\n"
        f"Thanks,\n{user.get('name', '')}\n{job.get('url', '')}"
    )
    return {"linkedin": note[:300], "email_subject": f"{job.get('title')} role, quick question",
            "email_body": body}


def followup_email(user: dict, job: dict, contact_name: str | None = None) -> tuple[str, str]:
    first = (contact_name or "").split(" ")[0] or "Hiring Team"
    subject = f"Following up: {job.get('title')} application"
    body = (
        f"Hi {first},\n\n"
        f"I wanted to follow up on my application for the {job.get('title')} role at "
        f"{company_name(job)}. I'm still very interested and think my experience is a strong "
        "match for what the team needs.\n\n"
        "Is there an update on timing, or anything else I can send over?\n\n"
        f"Thanks for your time,\n{user.get('name', '')}"
    )
    return subject, body


def thank_you_email(user: dict, job: dict, interviewer: str | None = None,
                    notes: str | None = None) -> tuple[str, str]:
    first = (interviewer or "").split(" ")[0] or "there"
    subject = f"Thank you, {job.get('title')} interview"
    body = (
        f"Hi {first},\n\n"
        f"Thank you for taking the time to talk with me about the {job.get('title')} role today. "
        f"I enjoyed hearing about {notes or '[ADD: something specific you discussed]'}.\n\n"
        f"Our conversation made me even more excited about the work at {company_name(job)}. "
        "Please let me know if there's anything else I can share.\n\n"
        f"Best,\n{user.get('name', '')}"
    )
    return subject, body
