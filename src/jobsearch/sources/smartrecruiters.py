"""SmartRecruiters public Posting API.

Endpoint: https://api.smartrecruiters.com/v1/companies/{company}/postings
"""
from __future__ import annotations

import httpx

from .base import html_to_text

API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
SECTIONS = ("jobDescription", "qualifications", "additionalInformation")


def fetch(slug: str, *, max_jobs: int = 200, timeout: float = 15.0) -> list[dict]:
    out: list[dict] = []
    offset = 0
    with httpx.Client(timeout=timeout) as client:
        while len(out) < max_jobs:
            resp = client.get(API.format(slug=slug), params={"limit": 100, "offset": offset})
            resp.raise_for_status()
            content = resp.json().get("content") or []
            if not content:
                break
            for p in content:
                if len(out) >= max_jobs:
                    break
                detail = client.get(f"{API.format(slug=slug)}/{p['id']}")
                body = detail.json() if detail.status_code == 200 else {}
                out.append(_normalize(slug, p, body))
            offset += 100
    return out


def _normalize(slug: str, p: dict, detail: dict) -> dict:
    sections = ((detail.get("jobAd") or {}).get("sections")) or {}
    parts = []
    for key in SECTIONS:
        sec = sections.get(key) or {}
        if sec.get("text"):
            parts.append(f"{sec.get('title') or key}\n{html_to_text(sec['text'])}")
    loc = p.get("location") or {}
    location = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
    if loc.get("remote"):
        location = f"{location} (Remote)" if location else "Remote"
    return {
        "id": f"smartrecruiters:{slug}:{p['id']}",
        "source": "smartrecruiters",
        "source_company": slug,
        "company_name": (p.get("company") or {}).get("name"),
        "title": p.get("name", ""),
        "location": location or None,
        "department": (p.get("department") or {}).get("label"),
        "description": "\n\n".join(parts),
        "url": detail.get("postingUrl") or detail.get("applyUrl")
               or f"https://jobs.smartrecruiters.com/{slug}/{p['id']}",
        "posted_at": p.get("releasedDate"),
    }
