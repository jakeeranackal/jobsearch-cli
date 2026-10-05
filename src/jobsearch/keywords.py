"""Keyword analysis: what a job (or a pile of jobs) asks for vs. what your resume shows.

Two entry points:
    analyze_job()   one posting, section-aware, with a per-term action
    market_terms()  many postings, "word cloud" style frequency across listings

Terms come from a skill lexicon (data/skills.txt) plus your configured extra
terms, so "Power BI", "PowerBI" and "power bi desktop" count as one skill.
Repeated phrases outside the lexicon are surfaced separately so domain words
("member experience", "sports analytics") aren't missed.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from pathlib import Path

from . import jd, resume_io

LEXICON_PATH = Path(__file__).parent / "data" / "skills.txt"

_STOP = set("""
a about above across after again against all also am an and any are as at be because been before
being below between both but by can could did do does doing down during each etc few for from
further had has have having he her here hers him his how i if in into is it its itself just
like may me might more most must my no nor not now of off on once only or other our ours out
over own per same shall she should so some such than that the their them then there these they
this those through to too under until up upon us very via was we were what when where which
while who whom why will with within would you your yours ability able strong excellent
experience experienced year years work working including include includes team teams
role new well using use used across preferred required plus within make ensure help
""".split())
_WORD = re.compile(r"[a-z][a-z0-9+#/&.-]*[a-z0-9+#]|[a-z]")

REQUIRED_W, TITLE_W, RESP_W, INTRO_W, PREF_W = 2.0, 3.0, 1.5, 1.0, 0.75


@dataclass(frozen=True)
class Skill:
    name: str
    aliases: tuple[str, ...]
    category: str
    pattern: re.Pattern

    def count(self, text: str) -> int:
        return len(self.pattern.findall(text)) if text else 0

    def forms(self, text: str) -> Counter:
        """Which alias spellings appear, e.g. {'powerbi': 2}."""
        return Counter(m.lower() for m in self.pattern.findall(text or ""))


def _compile(aliases: list[str]) -> re.Pattern:
    alts = sorted({a.strip() for a in aliases if a.strip()}, key=len, reverse=True)
    body = "|".join(re.escape(a) for a in alts)
    return re.compile(rf"(?<![A-Za-z0-9])({body})(?![A-Za-z0-9+#])", re.I)


def make_skill(name: str, aliases: list[str] | None = None, category: str = "custom") -> Skill:
    names = [name, *(aliases or [])]
    return Skill(name=name, aliases=tuple(names), category=category, pattern=_compile(names))


@lru_cache(maxsize=1)
def load_lexicon(path: Path = LEXICON_PATH) -> tuple[tuple[Skill, ...], tuple[tuple[str, ...], ...]]:
    skills: list[Skill] = []
    wording: list[tuple[str, ...]] = []
    category = "general"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            category = line[1:-1]
            continue
        if category == "wording":
            wording.append(tuple(w.strip().lower() for w in line.split("~") if w.strip()))
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        skills.append(make_skill(parts[0], parts[1:], category))
    return tuple(skills), tuple(wording)


def all_skills(extra_terms: list[str] | None = None) -> list[Skill]:
    skills, _ = load_lexicon()
    out = list(skills)
    known = {a.lower() for s in skills for a in s.aliases}
    for term in extra_terms or []:
        if term and term.lower() not in known:
            out.append(make_skill(term))
            known.add(term.lower())
    return out


@dataclass
class TermGap:
    term: str
    category: str
    job_count: int
    importance: str          # required | core duty | preferred | mentioned
    weight: float
    resume_bullets: int
    resume_skills: int
    resume_total: int
    status: str              # GOOD | STRENGTHEN | BURIED | WORDING | MISSING | NICE-TO-HAVE
    action: str
    job_form: str = ""
    resume_form: str = ""


@dataclass
class JobAnalysis:
    terms: list[TermGap] = field(default_factory=list)
    phrases: list[tuple[str, int, bool]] = field(default_factory=list)   # phrase, count, on resume
    wording: list[tuple[str, str]] = field(default_factory=list)          # (job word, your word)
    years_required: int | None = None
    salary: tuple[int, int] | None = None
    coverage: float = 0.0
    sections_found: list[str] = field(default_factory=list)

    @property
    def top_requirements(self) -> list[TermGap]:
        return [t for t in self.terms if t.importance in ("required", "core duty")][:8]

    @property
    def missing(self) -> list[TermGap]:
        return [t for t in self.terms if t.status == "MISSING"]


def _resume_parts(resume_text: str) -> tuple[str, str, str]:
    """(experience-ish text, skills text, everything) from a resume."""
    r = resume_io.parse(resume_text)
    exp, skills = [], []
    for s in r.sections:
        lines = [i.text for i in s.items]
        (skills if s.key == "skills" else exp).extend(lines)
    if not r.sections:
        exp = [resume_text]
    return "\n".join(exp), "\n".join(skills), resume_text


def _classify(t_imp: str, job_count: int, bullets: int, skills_only: int) -> tuple[str, str]:
    if bullets == 0 and skills_only == 0:
        if t_imp in ("required", "core duty"):
            return ("MISSING", "Not on your resume. If you've done it, add a bullet with a "
                               "result. If not, don't fake it; mention you're learning it.")
        return ("NICE-TO-HAVE", "Optional for them. Add only if it's real and fits.")
    if bullets == 0:
        if t_imp in ("required", "core duty"):
            return ("BURIED", "Only in your skills list. Prove it in 1-2 experience bullets "
                              "(what you built with it + the result).")
        return ("GOOD", "Listed in skills. Fine for a nice-to-have.")
    if job_count >= 3 and bullets == 1 and t_imp in ("required", "core duty"):
        return ("STRENGTHEN", f"They say it {job_count}x. Show it in 2+ bullets, ideally near the top.")
    return ("GOOD", "Covered.")


def _phrases(text: str, n_values=(2, 3)) -> Counter:
    words = _WORD.findall(text.lower())
    out: Counter = Counter()
    for n in n_values:
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if gram[0] in _STOP or gram[-1] in _STOP or any(len(w) < 3 for w in gram):
                continue
            if sum(w in _STOP for w in gram) > n // 2:
                continue
            out[" ".join(gram)] += 1
    return out


def analyze_job(job: dict, resume_text: str, extra_terms: list[str] | None = None) -> JobAnalysis:
    parsed = jd.parse(job.get("description") or "")
    title = job.get("title") or ""
    req = parsed.text(jd.REQUIRED)
    pref = parsed.text(jd.PREFERRED)
    resp = parsed.text(jd.RESPONSIBILITIES)
    intro = parsed.text(jd.INTRO)
    exp_text, skills_text, full_resume = _resume_parts(resume_text)

    result = JobAnalysis(
        years_required=jd.years_required(parsed),
        salary=jd.extract_salary(job.get("description") or ""),
        sections_found=[k for k in parsed.sections if parsed.sections[k]],
    )

    total_w = covered_w = 0.0
    for skill in all_skills(extra_terms):
        c_title, c_req, c_pref = skill.count(title), skill.count(req), skill.count(pref)
        c_resp, c_intro = skill.count(resp), skill.count(intro)
        job_count = c_title + c_req + c_pref + c_resp + c_intro
        if not job_count:
            continue
        weight = (TITLE_W * c_title + REQUIRED_W * c_req + RESP_W * c_resp
                  + INTRO_W * c_intro + PREF_W * c_pref)
        if c_title or c_req:
            importance = "required"
        elif c_resp or (c_intro and not c_pref):
            importance = "core duty"
        else:
            importance = "preferred" if c_pref else "mentioned"

        bullets = skill.count(exp_text)
        in_skills = skill.count(skills_text)
        status, action = _classify(importance, job_count, bullets, in_skills)

        job_forms = skill.forms("\n".join((title, req, pref, resp, intro)))
        res_forms = skill.forms(full_resume)
        job_form = job_forms.most_common(1)[0][0] if job_forms else ""
        res_form = res_forms.most_common(1)[0][0] if res_forms else ""
        if status == "GOOD" and res_form and job_form and res_form != job_form \
                and job_form not in res_forms:
            status, action = "WORDING", f"Use their wording \"{job_form}\" (you wrote \"{res_form}\")."

        result.terms.append(TermGap(
            term=skill.name, category=skill.category, job_count=job_count,
            importance=importance, weight=round(weight, 2), resume_bullets=bullets,
            resume_skills=in_skills, resume_total=bullets + in_skills, status=status,
            action=action, job_form=job_form, resume_form=res_form,
        ))
        if importance in ("required", "core duty"):
            total_w += weight
            if bullets + in_skills:
                covered_w += weight
    result.terms.sort(key=lambda t: t.weight, reverse=True)
    result.coverage = round(covered_w / total_w, 3) if total_w else 0.0

    known = {a.lower() for s in all_skills(extra_terms) for a in s.aliases}
    resume_lower = full_resume.lower()
    for phrase, n in _phrases("\n".join((title, req, resp, intro, pref))).most_common(40):
        if n < 2 or phrase in known or any(k in phrase.split() for k in ("equal", "benefits")):
            continue
        result.phrases.append((phrase, n, phrase in resume_lower))
        if len(result.phrases) >= 12:
            break

    _, groups = load_lexicon()
    job_lower = parsed.relevant_text.lower() + " " + title.lower()
    for group in groups:
        job_words = [w for w in group if re.search(rf"\b{re.escape(w)}\b", job_lower)]
        res_words = [w for w in group if re.search(rf"\b{re.escape(w)}\b", resume_lower)]
        for jw in job_words:
            if jw not in res_words and res_words:
                result.wording.append((jw, res_words[0]))

    # A "missing" term you cover under a near-synonym is a wording fix, not a gap.
    swaps = dict(result.wording)
    for t in result.terms:
        if t.status != "MISSING":
            continue
        mine = swaps.get(t.term.lower()) or swaps.get(t.job_form)
        if mine:
            t.status = "WORDING"
            t.action = (f"They say \"{t.job_form or t.term.lower()}\", you say \"{mine}\". "
                        "Use their word where it's accurate.")
    return result


def coverage(job: dict, resume_text: str, extra_terms: list[str] | None = None) -> float:
    return analyze_job(job, resume_text, extra_terms).coverage


@dataclass
class MarketTerm:
    term: str
    category: str
    jobs_mentioning: int
    jobs_requiring: int
    share: float
    on_resume: bool


def market_terms(jobs: list[dict], resume_text: str = "",
                 extra_terms: list[str] | None = None) -> tuple[list[MarketTerm], list[tuple[str, int]]]:
    """Across many postings: how many mention / require each term. Returns (skills, phrases)."""
    n = len(jobs) or 1
    mention: Counter = Counter()
    require: Counter = Counter()
    phrase_docs: Counter = Counter()
    skills = all_skills(extra_terms)
    for job in jobs:
        parsed = jd.parse(job.get("description") or "")
        relevant = (job.get("title") or "") + "\n" + parsed.relevant_text
        req = (job.get("title") or "") + "\n" + parsed.text(jd.REQUIRED)
        for s in skills:
            if s.count(relevant):
                mention[s.name] += 1
                if s.count(req):
                    require[s.name] += 1
        phrase_docs.update(set(_phrases(relevant)))
    by_name = {s.name: s for s in skills}
    out = [
        MarketTerm(term=name, category=by_name[name].category, jobs_mentioning=c,
                   jobs_requiring=require[name], share=round(c / n, 3),
                   on_resume=bool(by_name[name].count(resume_text)))
        for name, c in mention.most_common()
    ]
    known = {a.lower() for s in skills for a in s.aliases}
    min_docs = max(2, n // 10)
    phrases = [(p, c) for p, c in phrase_docs.most_common(80) if c >= min_docs and p not in known][:25]
    return out, phrases


def cloud_html(terms: list[MarketTerm], phrases: list[tuple[str, int]], n_jobs: int,
               title: str = "Job keyword cloud") -> str:
    """Self-contained HTML word cloud. Green = on your resume, red = missing."""
    if not terms:
        return "<p>No terms found.</p>"
    top = max(t.jobs_mentioning for t in terms)
    spans = []
    for t in terms[:80]:
        size = 0.85 + 2.6 * (t.jobs_mentioning / top)
        cls = "have" if t.on_resume else "miss"
        tip = f"{t.jobs_mentioning}/{n_jobs} postings, required in {t.jobs_requiring}"
        spans.append(f'<span class="{cls}" style="font-size:{size:.2f}rem" title="{escape(tip)}">'
                     f'{escape(t.term)}</span>')
    rows = "".join(
        f"<tr><td>{escape(t.term)}</td><td>{t.jobs_mentioning}</td><td>{t.jobs_requiring}</td>"
        f"<td>{t.share:.0%}</td><td class=\"{'have' if t.on_resume else 'miss'}\">"
        f"{'yes' if t.on_resume else 'missing'}</td></tr>"
        for t in terms[:60]
    )
    phrase_list = "".join(f"<li>{escape(p)} <small>({c})</small></li>" for p, c in phrases)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{ --bg:#f7f5f0; --fg:#1d1c1a; --muted:#6b675f; --have:#1f7a4d; --miss:#b3361f; --card:#fffdf8; --line:#e4dfd3; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#151513; --fg:#ece8df; --muted:#9a958a; --have:#5cc48f; --miss:#ef7a62; --card:#1e1d1a; --line:#33312c; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 Georgia, 'Iowan Old Style', serif; }}
main {{ max-width:980px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:2rem; margin:0 0 4px; letter-spacing:-.01em; }}
p.sub {{ color:var(--muted); margin:0 0 24px; font-family:system-ui, sans-serif; font-size:.9rem; }}
.cloud {{ background:var(--card); border:1px solid var(--line); border-radius:6px; padding:28px; line-height:2.4;
  text-align:center; box-shadow:0 1px 0 var(--line), 0 12px 30px -20px rgba(0,0,0,.35); }}
.cloud span {{ margin:0 .45em; white-space:nowrap; cursor:default; font-weight:600; }}
.have {{ color:var(--have); }} .miss {{ color:var(--miss); }}
.grid {{ display:grid; grid-template-columns:2fr 1fr; gap:24px; margin-top:28px; }}
@media (max-width:720px) {{ .grid {{ grid-template-columns:1fr; }} }}
table {{ width:100%; border-collapse:collapse; font-family:system-ui, sans-serif; font-size:.85rem; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:500; }}
ul {{ font-family:system-ui, sans-serif; font-size:.9rem; padding-left:18px; }}
small {{ color:var(--muted); }}
</style></head><body><main>
<h1>{escape(title)}</h1>
<p class="sub">{n_jobs} postings analyzed. Bigger = mentioned in more postings.
<span class="have">Green</span> is already on your resume, <span class="miss">red</span> is missing. Hover a word for counts.</p>
<div class="cloud">{''.join(spans)}</div>
<div class="grid">
<section><h2>Top terms</h2><table><tr><th>Term</th><th>Mentioned</th><th>Required</th><th>Share</th><th>Resume</th></tr>{rows}</table></section>
<section><h2>Other repeated phrases</h2><ul>{phrase_list or '<li>None</li>'}</ul></section>
</div></main></body></html>"""
