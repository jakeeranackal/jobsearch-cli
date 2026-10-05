"""Lever postings public API.

Endpoint: https://api.lever.co/v0/postings/{site}?mode=json
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import html_to_text

API = "https://api.lever.co/v0/postings/{slug}"


def fetch(slug: str, *, timeout: float = 15.0) -> list[dict]:
    """Return normalized job dicts for a given Lever site slug."""
    url = API.format(slug=slug)
    resp = httpx.get(url, params={"mode": "json"}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    out: list[dict] = []
    for j in data:
        job_id = f"lever:{slug}:{j['id']}"
        cats = j.get("categories") or {}
        # Lever's description text is split across a few fields; concatenate.
        desc_parts = [html_to_text(j.get("description")) or j.get("descriptionPlain")]
        for L in j.get("lists", []) or []:
            desc_parts.append(L.get("text", ""))
            desc_parts.append(html_to_text(L.get("content", "")))
        desc_parts.append(html_to_text(j.get("additional")) or j.get("additionalPlain"))
        description = "\n".join(p for p in desc_parts if p)

        out.append({
            "id": job_id,
            "source": "lever",
            "source_company": slug,
            "title": j.get("text", ""),
            "location": cats.get("location"),
            "department": cats.get("department") or cats.get("team"),
            "description": description,
            "url": j.get("hostedUrl", ""),
            "posted_at": _ms_to_iso(j.get("createdAt")),
            "salary_min": (j.get("salaryRange") or {}).get("min"),
            "salary_max": (j.get("salaryRange") or {}).get("max"),
        })
    return out


def _ms_to_iso(ms) -> str | None:
    if not isinstance(ms, (int, float)):
        return ms
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")
