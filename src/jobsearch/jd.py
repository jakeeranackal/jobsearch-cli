"""Job description parsing: sections, salary, years of experience.

Postings are free text, so this is heuristic. Headings are recognized by a
short line that starts with a known phrase ("Requirements", "What you'll do",
"Nice to have"). Anything unrecognized stays in the current section.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REQUIRED = "required"
PREFERRED = "preferred"
RESPONSIBILITIES = "responsibilities"
INTRO = "intro"
IGNORED = "ignored"

_HEADINGS: list[tuple[str, tuple[str, ...]]] = [
    (PREFERRED, (
        "preferred", "nice to have", "nice-to-have", "bonus", "pluses", "plus if",
        "even better", "ideally", "it would be great", "extra credit", "desired",
        "what we value", "nice-to-haves", "nice to haves",
    )),
    (REQUIRED, (
        "requirements", "required", "qualifications", "minimum qualifications",
        "basic qualifications", "what you'll need", "what you will need", "what you need",
        "what you bring", "what we're looking for", "what we are looking for",
        "you have", "you might be a fit", "who you are", "about you", "must have",
        "must-have", "skills and experience", "experience and skills", "your background",
        "skills", "you'll be successful", "you will be successful", "to be successful",
        "the ideal candidate", "competencies", "your expertise", "your skills",
        "your experience", "what you'll bring", "what you will bring", "you bring", "what we need",
        "required skills", "minimum requirements", "basic requirements", "key qualifications",
        "experience & skills", "skills & experience", "skills & qualifications",
        "we're looking for", "we are looking for", "who we're looking for",
        "what we require", "who you'll be", "technologies we use", "tech stack",
    )),
    (RESPONSIBILITIES, (
        "responsibilities", "what you'll do", "what you will do", "what you'll be doing",
        "your role", "the role", "role overview", "day to day", "day-to-day", "duties",
        "in this role", "your impact", "key responsibilities", "the opportunity",
        "what you'll work on", "job description", "position summary", "overview",
        "a typical day", "the difference you will make", "your day", "about the role",
        "about the job", "job summary", "what you'll achieve", "your mission", "the work",
        "core responsibilities", "no two days", "you can expect to", "what you will be doing",
    )),
    (IGNORED, (
        "about us", "about the company", "about the team", "who we are", "our mission",
        "benefits", "perks", "what we offer", "why join", "why you'll love",
        "compensation", "salary", "pay range", "pay transparency", "total rewards",
        "equal opportunity", "eeo", "accommodation", "diversity", "our values",
        "location", "work environment", "physical requirements", "privacy",
        "the community you will join", "how we'll take care of you", "our commitment",
        "your location", "equal employment", "who you'll work with", "life at", "working at",
        "about our", "what's in it for you", "we offer", "where you'll be",
    )),
]

_BULLET_PREFIX = re.compile(r"^[\-\*•●▪–]\s*")
_MONEY = r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s?[kK]?)"
_SALARY_RANGE = re.compile(_MONEY + r"\s*(?:-|–|—|to)\s*\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s?[kK]?)")
_HOURLY = re.compile(r"(per hour|/\s?hr|/\s?hour|hourly|an hour)", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*years?", re.I)


@dataclass
class ParsedJD:
    sections: dict[str, list[str]] = field(default_factory=dict)

    def text(self, *names: str) -> str:
        return "\n".join(ln for n in names for ln in self.sections.get(n, []))

    @property
    def relevant_text(self) -> str:
        return self.text(INTRO, RESPONSIBILITIES, REQUIRED, PREFERRED)


def _heading_section(line: str) -> str | None:
    s = _BULLET_PREFIX.sub("", line).strip().rstrip(":").strip().lower()
    s = s.replace("’", "'")
    if not s or len(s) > 90 or s.endswith("."):
        return None
    for section, phrases in _HEADINGS:
        for p in phrases:
            if s == p or s.startswith(p + " ") or s.startswith(p + ":") or s.startswith(p + ","):
                return section
    return None


def _restore_lines(text: str) -> str:
    """Old single-line descriptions: break before 'Heading:' patterns."""
    if text.count("\n") >= 3:
        return text
    phrases = sorted({p for _, ps in _HEADINGS for p in ps}, key=len, reverse=True)
    rx = re.compile(r"\s(" + "|".join(re.escape(p) for p in phrases) + r")\s*:", re.I)
    text = rx.sub(lambda m: "\n" + m.group(1) + ":\n", text)
    return re.sub(r"\s[•●]\s", "\n- ", text)


def parse(description: str) -> ParsedJD:
    parsed = ParsedJD()
    current = INTRO
    for raw in _restore_lines(description or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        sec = _heading_section(line)
        if sec:
            current = sec
            continue
        if "equal opportunity" in line.lower() or "regard to race" in line.lower():
            parsed.sections.setdefault(IGNORED, []).append(line)
            continue
        parsed.sections.setdefault(current, []).append(line)
    return parsed


def _to_number(s: str) -> float:
    s = s.replace(",", "").replace(" ", "")
    mult = 1000 if s.lower().endswith("k") else 1
    return float(s.rstrip("kK")) * mult


def extract_salary(text: str) -> tuple[int, int] | None:
    """Return (min, max) annual salary if a range is stated. Hourly is annualized."""
    for m in _SALARY_RANGE.finditer(text or ""):
        lo, hi = _to_number(m.group(1)), _to_number(m.group(2))
        if hi < lo:
            continue
        window = text[max(0, m.start() - 40): m.end() + 40]
        if _HOURLY.search(window) or hi < 300:
            lo, hi = lo * 2080, hi * 2080
        if hi < 15000:
            continue
        return int(lo), int(hi)
    return None


def years_required(parsed: ParsedJD) -> int | None:
    """Smallest 'N+ years' in the requirements; None if not stated."""
    text = parsed.text(REQUIRED) or parsed.relevant_text
    vals = [int(m.group(1)) for m in _YEARS.finditer(text) if 0 < int(m.group(1)) < 30]
    return min(vals) if vals else None
