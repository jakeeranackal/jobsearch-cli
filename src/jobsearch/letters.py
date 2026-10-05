"""Drafts of everything you send: cover letters, outreach, follow-ups, thank-yous.

Each function uses Claude when available and a plain template otherwise.
Everything is a draft; nothing here sends anything.
"""
from __future__ import annotations

from . import drafter, keywords, llm, resume_io
from .config import company_name

_VOICE = """Write like a sharp, friendly early-career professional. Plain words, short
sentences, no clichés ("I am excited to apply", "passionate", "synergy", "leverage"),
no exclamation marks, no emojis. Only state facts that are in the resume or notes given.
If a fact you'd need is missing, write [ADD: what's needed] instead of inventing it."""


def _top_bullets(resume_text: str, analysis: keywords.JobAnalysis, n: int = 4) -> list[str]:
    weights = {t.term: t.weight for t in analysis.terms}
    skills = keywords.all_skills(list(weights))
    scored = []
    for b in resume_io.parse(resume_text).bullets():
        score = sum(weights.get(s.name, 0) for s in skills if s.count(b))
        scored.append((score, b))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [b for s, b in scored[:n]] or drafter.extract_highlights(resume_text, n)


def cover_letter(cfg: dict, user: dict, job: dict, resume_text: str,
                 analysis: keywords.JobAnalysis, brief: str | None = None,
                 track: str = "", score: float = 0.0) -> str:
    company = company_name(job)
    if llm.available(cfg):
        reqs = ", ".join(t.term for t in analysis.top_requirements[:5])
        prompt = (
            f"Write a cover letter for {user.get('name')} applying to {job.get('title')} at {company}.\n"
            f"Their top requirements: {reqs}\n\n"
            f"POSTING:\n{(job.get('description') or '')[:8000]}\n\n"
            f"RESUME:\n{resume_text}\n\n"
            + (f"COMPANY NOTES:\n{brief}\n\n" if brief else "")
            + "Structure: 1) one-line hook naming the role and the single strongest match; "
              "2) a short paragraph with one concrete story from the resume that proves their "
              "#1 requirement, with the result; 3) two or three quick proof points for other "
              "requirements; 4) one specific line on why this company; 5) a plain close. "
              "250-330 words. Start with 'Dear Hiring Team,' and end with the candidate's name."
        )
        body = llm.ask_text(cfg, _VOICE, prompt)
        header = "\n".join(x for x in (user.get("name"), " | ".join(
            v for v in (user.get("email"), user.get("phone"), user.get("location")) if v)) if x)
        return f"{header}\n\n{body}\n"
    matched = [t.term for t in analysis.top_requirements if t.resume_total][:4]
    return drafter.render(
        user=user, job={**job, "source_company": company}, resume_track=track, score=score,
        matched_keywords=matched, resume_highlights=_top_bullets(resume_text, analysis),
    )


def outreach(cfg: dict, user: dict, job: dict, analysis: keywords.JobAnalysis,
             resume_text: str, contact_name: str | None = None,
             referral: bool = False) -> dict[str, str]:
    """Return {'linkedin': <=300 char note, 'email_subject': ..., 'email_body': ...}."""
    company = company_name(job)
    first = (contact_name or "").split(" ")[0] or "there"
    strengths = [t.term for t in analysis.top_requirements if t.resume_total][:2]
    if llm.available(cfg):
        schema = {
            "type": "object",
            "properties": {
                "linkedin": {"type": "string"},
                "email_subject": {"type": "string"},
                "email_body": {"type": "string"},
            },
            "required": ["linkedin", "email_subject", "email_body"],
            "additionalProperties": False,
        }
        kind = "a former colleague/connection, asking for a referral" if referral \
            else "a recruiter or hiring manager they don't know"
        prompt = (
            f"Candidate {user.get('name')} wants to reach {contact_name or 'someone'} at {company}, "
            f"{kind}, about the {job.get('title')} role ({job.get('url')}).\n"
            f"Their strongest matches: {', '.join(strengths) or 'see resume'}.\n\nRESUME:\n{resume_text}\n\n"
            "Write: a LinkedIn connection note under 280 characters; a cold email of 80-120 words "
            "with a specific subject line. Ask for one small thing (a 15-minute chat, or "
            "a referral if they know the candidate). No attachments mentioned."
        )
        return llm.ask_json(cfg, _VOICE, prompt, schema, effort="low")
    skills = " and ".join(strengths)
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


def followup_email(cfg: dict, user: dict, job: dict, status: str,
                   contact_name: str | None = None) -> tuple[str, str]:
    company = company_name(job)
    first = (contact_name or "").split(" ")[0] or "Hiring Team"
    if llm.available(cfg):
        prompt = (
            f"{user.get('name')} applied for {job.get('title')} at {company}; current status: {status}. "
            f"Write a polite follow-up email to {contact_name or 'the hiring team'} of 60-90 words: "
            "restate interest, one line on fit, ask about timeline. Return the subject on the "
            "first line prefixed 'Subject: ', then a blank line, then the body."
        )
        text = llm.ask_text(cfg, _VOICE, prompt, effort="low")
        subject, _, body = text.partition("\n")
        return subject.removeprefix("Subject:").strip(), body.strip()
    subject = f"Following up: {job.get('title')} application"
    body = (
        f"Hi {first},\n\n"
        f"I wanted to follow up on my application for the {job.get('title')} role at {company}. "
        "I'm still very interested and think my experience is a strong match for what the team needs.\n\n"
        "Is there an update on timing, or anything else I can send over?\n\n"
        f"Thanks for your time,\n{user.get('name', '')}"
    )
    return subject, body


def thank_you_email(cfg: dict, user: dict, job: dict, interviewer: str | None = None,
                    notes: str | None = None) -> tuple[str, str]:
    company = company_name(job)
    first = (interviewer or "").split(" ")[0] or "there"
    if llm.available(cfg):
        prompt = (
            f"{user.get('name')} just interviewed for {job.get('title')} at {company} with "
            f"{interviewer or 'the team'}. Notes from the conversation: {notes or 'none given'}.\n"
            "Write a thank-you email of 70-110 words that references one specific thing discussed "
            "(use [ADD: something specific you discussed] if no notes), restates fit in one line, "
            "and closes simply. Subject on first line prefixed 'Subject: ', blank line, then body."
        )
        text = llm.ask_text(cfg, _VOICE, prompt, effort="low")
        subject, _, body = text.partition("\n")
        return subject.removeprefix("Subject:").strip(), body.strip()
    subject = f"Thank you, {job.get('title')} interview"
    body = (
        f"Hi {first},\n\n"
        f"Thank you for taking the time to talk with me about the {job.get('title')} role today. "
        f"I enjoyed hearing about {notes or '[ADD: something specific you discussed]'}.\n\n"
        f"Our conversation made me even more excited about the work at {company}. "
        "Please let me know if there's anything else I can share.\n\n"
        f"Best,\n{user.get('name', '')}"
    )
    return subject, body
