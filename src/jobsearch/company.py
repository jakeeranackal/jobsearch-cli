"""Company research: a one-page brief, and discovering similar companies to watch."""
from __future__ import annotations

import sqlite3
from collections import Counter
from urllib.parse import quote

import httpx

from . import jd, llm
from .config import company_name
from .sources import ashby, greenhouse, lever, smartrecruiters, workable

PROBES = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "workable": workable.fetch,
    "smartrecruiters": smartrecruiters.fetch,
}


def wikipedia_summary(name: str, timeout: float = 10.0) -> str | None:
    try:
        r = httpx.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(name.replace(' ', '_'))}",
            timeout=timeout, headers={"User-Agent": "jobsearch-cli"}, follow_redirects=True,
        )
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("type") == "disambiguation":
        return None
    return data.get("extract")


def brief(conn: sqlite3.Connection, job: dict, cfg: dict) -> str:
    name = company_name(job)
    rows = conn.execute(
        "SELECT title, location, department FROM jobs WHERE source_company = ? AND is_open = 1",
        (job["source_company"],),
    ).fetchall()
    depts = Counter(r["department"] for r in rows if r["department"])
    locs = Counter(r["location"] for r in rows if r["location"])
    wiki = wikipedia_summary(name)
    about = jd.parse(job.get("description") or "").text(jd.IGNORED)[:2500]

    lines = [f"# {name}: company brief", ""]
    if wiki:
        lines += ["## Overview (Wikipedia; check it's the right company)", wiki, ""]
    lines += [
        "## Hiring right now",
        f"- {len(rows)} open roles tracked",
        *(f"- {d}: {c} roles" for d, c in depts.most_common(5)),
        *(f"- Location: {l} ({c})" for l, c in locs.most_common(3)),
        "",
    ]
    if llm.available(cfg):
        prompt = (
            f"Company: {name}\nRole applied for: {job.get('title')}\n\n"
            f"Wikipedia: {wiki or 'n/a'}\n\nFrom their own postings:\n{about or 'n/a'}\n\n"
            f"Open roles: {', '.join(sorted({r['title'] for r in rows})[:30])}\n\n"
            "Using only the text above, write: 3 bullets on what they do and who for; 2 bullets on "
            "what their hiring suggests they're investing in; 3 angles for a genuine 'why this "
            "company' answer; 3 smart questions to ask in an interview. Say 'unknown' where the "
            "text doesn't support a claim. Markdown, short."
        )
        lines += ["## Analysis", llm.ask_text(cfg, "You are a concise career researcher.", prompt,
                                              effort="low"), ""]
    else:
        lines += ["## To fill in",
                  "- What they sell and to whom:",
                  "- Recent news (search: company name + news):",
                  "- Why you, specifically, want to work here:", ""]
    return "\n".join(lines)


def probe(source: str, slug: str) -> int | None:
    """Number of open jobs on that board, or None if the slug doesn't exist."""
    fetch = PROBES.get(source)
    if not fetch:
        return None
    try:
        return len(fetch(slug))
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def suggest(cfg: dict, like: list[str], roles: list[str], locations: list[str]) -> list[dict]:
    """Ask Claude for similar companies, then keep only those with a live job board."""
    if not llm.available(cfg):
        raise llm.LLMError("Company suggestions need a Claude API key.")
    schema = {
        "type": "object",
        "properties": {
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "why": {"type": "string"},
                        "ats_guesses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source": {"type": "string", "enum": list(PROBES)},
                                    "slug": {"type": "string"},
                                },
                                "required": ["source", "slug"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["name", "why", "ats_guesses"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["companies"],
        "additionalProperties": False,
    }
    prompt = (
        f"I like these companies: {', '.join(like)}. Target roles: {', '.join(roles) or 'any'}. "
        f"Locations: {', '.join(locations) or 'any'}.\n"
        "Suggest 15 similar companies (size, industry, culture) likely to hire for these roles. "
        "For each, guess which job board it uses and the board slug (e.g. greenhouse 'airbnb', "
        "lever 'netflix'). Give up to 3 guesses per company."
    )
    data = llm.ask_json(cfg, "You know the tech and business job market well.", prompt, schema,
                        effort="low")
    out = []
    for c in data["companies"]:
        for g in c["ats_guesses"]:
            n = probe(g["source"], g["slug"].strip().lower())
            if n:
                out.append({"name": c["name"], "why": c["why"], "source": g["source"],
                            "slug": g["slug"].strip().lower(), "open_jobs": n})
                break
    return out
