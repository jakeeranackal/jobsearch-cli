"""Generic RSS/Atom feed adapter.

Use this for any career page that publishes a feed — many ATSs and CMSs
expose one even when their API isn't public.
"""
from __future__ import annotations

import hashlib

import feedparser

from .base import strip_html


def fetch(feed_name: str, feed_url: str) -> list[dict]:
    """Return normalized job dicts from an RSS/Atom feed."""
    parsed = feedparser.parse(feed_url)
    out: list[dict] = []
    for entry in parsed.entries:
        link = entry.get("link", "")
        # Some feeds reuse guids per re-publish; hash link + title for stability.
        raw_id = entry.get("id") or entry.get("guid") or f"{link}|{entry.get('title','')}"
        digest = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:16]
        job_id = f"rss:{feed_name}:{digest}"

        description = strip_html(
            entry.get("summary") or entry.get("description") or ""
        )
        # Some Atom feeds put the long body in entry.content[0].value
        if not description and entry.get("content"):
            description = strip_html(entry.content[0].get("value", ""))

        out.append({
            "id": job_id,
            "source": "rss",
            "source_company": feed_name,
            "title": entry.get("title", ""),
            "location": None,           # RSS feeds rarely include structured location
            "department": None,
            "description": description,
            "url": link,
            "posted_at": entry.get("published") or entry.get("updated"),
        })
    return out
