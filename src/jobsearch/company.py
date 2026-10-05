"""Company research: a one-page brief, and checking whether a job board slug is live."""
from __future__ import annotations

import sqlite3
from collections import Counter
from urllib.parse import quote

import httpx

from . import jd
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


def brief(conn: sqlite3.Connection, job: dict) -> str:
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
    titles = sorted({r["title"] for r in rows})
    if titles:
        lines += ["## Other open roles", *(f"- {t}" for t in titles[:25]), ""]
    if about:
        lines += ["## In their own words (from the posting)", about, ""]
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

