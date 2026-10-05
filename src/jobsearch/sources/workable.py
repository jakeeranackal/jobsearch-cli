"""Workable public job widget API.

Endpoint: https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true
"""
from __future__ import annotations

import httpx

from .base import html_to_text

API = "https://apply.workable.com/api/v1/widget/accounts/{slug}"


def fetch(slug: str, *, timeout: float = 15.0) -> list[dict]:
    resp = httpx.get(API.format(slug=slug), params={"details": "true"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    out: list[dict] = []
    for j in data.get("jobs", []):
        location = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        if j.get("telecommuting"):
            location = f"{location} (Remote)" if location else "Remote"
        out.append({
            "id": f"workable:{slug}:{j.get('shortcode')}",
            "source": "workable",
            "source_company": slug,
            "company_name": data.get("name"),
            "title": j.get("title", ""),
            "location": location or None,
            "department": j.get("department"),
            "description": html_to_text(j.get("description")),
            "url": j.get("url") or j.get("application_url", ""),
            "posted_at": j.get("published_on") or j.get("created_at"),
        })
    return out
