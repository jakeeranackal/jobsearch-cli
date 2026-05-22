"""Greenhouse Job Board public API.

Docs: https://developers.greenhouse.io/job-board.html
Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""
from __future__ import annotations

import httpx

from .base import strip_html

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def fetch(slug: str, *, timeout: float = 15.0) -> list[dict]:
    """Return normalized job dicts for a given Greenhouse board slug."""
    url = API.format(slug=slug)
    resp = httpx.get(url, params={"content": "true"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    out: list[dict] = []
    for j in data.get("jobs", []):
        job_id = f"greenhouse:{slug}:{j['id']}"
        out.append({
            "id": job_id,
            "source": "greenhouse",
            "source_company": slug,
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name"),
            "department": _first_dept(j),
            "description": strip_html(j.get("content", "")),
            "url": j.get("absolute_url", ""),
            "posted_at": j.get("updated_at"),
        })
    return out


def _first_dept(job: dict) -> str | None:
    depts = job.get("departments") or []
    if depts and isinstance(depts, list):
        return depts[0].get("name")
    return None
