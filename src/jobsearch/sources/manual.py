"""Jobs added by hand: a pasted listing, a text file, or a single URL.

LinkedIn and Indeed can't be pulled programmatically (login walls and ToS),
so the supported path for those is copy the posting text and paste it.
For links on a known ATS we hit that ATS's public API for clean data.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

import httpx

from .base import html_to_text

ATS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)(?:/jobs/(\d+))?")),
    ("lever", re.compile(r"jobs\.lever\.co/([\w.-]+)(?:/([0-9a-f-]{36}))?")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)(?:/([0-9a-f-]{36}))?")),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)(?:/j/(\w+))?")),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)(?:/(\d+))?")),
]
_WORKDAY_RE = re.compile(r"([\w-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)")
_BLOCKED_HOSTS = ("linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com")


def detect_ats(url: str) -> tuple[str, str, str | None] | None:
    """Return (source, slug, job_id_or_None) for a known ATS URL."""
    m = _WORKDAY_RE.search(url)
    if m:
        return "workday", f"{m.group(1)}/{m.group(2)}", None
    for source, rx in ATS_PATTERNS:
        m = rx.search(url)
        if m:
            return source, m.group(1), m.group(2)
    return None


def is_blocked(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host.endswith(h) for h in _BLOCKED_HOSTS)


def from_text(text: str, *, title: str, company: str, location: str | None = None,
              url: str = "") -> dict:
    digest = hashlib.sha1(f"{company}|{title}|{text[:500]}".encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-") or "manual"
    return {
        "id": f"manual:{slug}:{digest}",
        "source": "manual",
        "source_company": slug,
        "company_name": company,
        "title": title,
        "location": location,
        "department": None,
        "description": text.strip(),
        "url": url,
        "posted_at": None,
    }


def fetch_url(url: str, *, timeout: float = 20.0) -> dict | None:
    """Fetch one posting. Uses the ATS API where we can, else raw page text.

    Returns a partial job dict; title/company may be missing for generic pages.
    """
    ats = detect_ats(url)
    if ats and ats[2]:
        source, slug, remote_id = ats
        if source == "greenhouse":
            r = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{remote_id}",
                          timeout=timeout)
            r.raise_for_status()
            j = r.json()
            return {
                "id": f"greenhouse:{slug}:{remote_id}", "source": "greenhouse",
                "source_company": slug, "title": j.get("title", ""),
                "location": (j.get("location") or {}).get("name"),
                "description": html_to_text(j.get("content")),
                "url": j.get("absolute_url") or url, "posted_at": j.get("updated_at"),
            }
        if source == "lever":
            r = httpx.get(f"https://api.lever.co/v0/postings/{slug}/{remote_id}", timeout=timeout)
            r.raise_for_status()
            j = r.json()
            parts = [html_to_text(j.get("description"))]
            for L in j.get("lists") or []:
                parts += [L.get("text", ""), html_to_text(L.get("content"))]
            parts.append(html_to_text(j.get("additional")))
            return {
                "id": f"lever:{slug}:{remote_id}", "source": "lever", "source_company": slug,
                "title": j.get("text", ""), "location": (j.get("categories") or {}).get("location"),
                "description": "\n".join(p for p in parts if p),
                "url": j.get("hostedUrl") or url, "posted_at": None,
            }
    r = httpx.get(url, timeout=timeout, follow_redirects=True,
                  headers={"User-Agent": "Mozilla/5.0 jobsearch-cli"})
    r.raise_for_status()
    html = r.text
    html = re.sub(r"<(script|style|nav|footer|header)\b.*?</\1>", " ", html, flags=re.S | re.I)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return {
        "title": html_to_text(title_m.group(1)) if title_m else "",
        "description": html_to_text(html),
        "url": url,
    }
