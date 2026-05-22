"""Ashby job board public API.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true
"""
from __future__ import annotations

import httpx

from .base import strip_html

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def fetch(slug: str, *, timeout: float = 15.0) -> list[dict]:
    """Return normalized job dicts for a given Ashby job board slug."""
    url = API.format(slug=slug)
    resp = httpx.get(url, params={"includeCompensation": "true"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    out: list[dict] = []
    for j in data.get("jobs", []):
        job_id = f"ashby:{slug}:{j['id']}"
        out.append({
            "id": job_id,
            "source": "ashby",
            "source_company": slug,
            "title": j.get("title", ""),
            "location": j.get("location"),
            "department": j.get("department") or j.get("team"),
            "description": strip_html(
                j.get("descriptionHtml") or j.get("descriptionPlain") or ""
            ),
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
            "posted_at": j.get("publishedAt") or j.get("updatedAt"),
        })
    return out
