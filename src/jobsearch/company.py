"""Check whether a company's job board slug is live (used when adding companies)."""
from __future__ import annotations

import httpx

from .sources import ashby, greenhouse, lever, smartrecruiters, workable

PROBES = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "workable": workable.fetch,
    "smartrecruiters": smartrecruiters.fetch,
}


def probe(source: str, slug: str) -> int | None:
    """Number of open jobs on that board, or None if the slug doesn't exist."""
    fetch = PROBES.get(source)
    if not fetch:
        return None
    try:
        return len(fetch(slug))
    except (httpx.HTTPError, ValueError, KeyError):
        return None
