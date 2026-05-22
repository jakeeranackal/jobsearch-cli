"""Lever postings public API.

Endpoint: https://api.lever.co/v0/postings/{site}?mode=json
"""
from __future__ import annotations

import httpx

from .base import strip_html

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
        desc_parts = [j.get("descriptionPlain") or strip_html(j.get("description"))]
        for L in j.get("lists", []) or []:
            desc_parts.append(L.get("text", ""))
            desc_parts.append(strip_html(L.get("content", "")))
        desc_parts.append(j.get("additionalPlain") or strip_html(j.get("additional")))
        description = " ".join(p for p in desc_parts if p)

        out.append({
            "id": job_id,
            "source": "lever",
            "source_company": slug,
            "title": j.get("text", ""),
            "location": cats.get("location"),
            "department": cats.get("department") or cats.get("team"),
            "description": description,
            "url": j.get("hostedUrl", ""),
            "posted_at": j.get("createdAt"),
        })
    return out
