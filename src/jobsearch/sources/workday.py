"""Workday career sites (the public JSON the career page itself calls).

Config slug is "host/site", e.g. "nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite".
Workday boards can hold thousands of postings, so we search with the
configured role terms and cap how many detail pages we pull.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx

from .base import html_to_text

_POSTED_RE = re.compile(r"(\d+)\+?\s+day", re.I)


def split_slug(slug: str) -> tuple[str, str, str]:
    """Return (host, tenant, site) from 'host/site' or a full careers URL."""
    s = re.sub(r"^https?://", "", slug.strip()).strip("/")
    host, _, rest = s.partition("/")
    parts = [p for p in rest.split("/") if p]
    # Drop a locale segment like en-US
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]
    if not parts:
        raise ValueError(f"Workday slug needs a site path: {slug}")
    tenant = host.split(".")[0]
    return host, tenant, parts[0]


def fetch(slug: str, *, search: str = "", max_jobs: int = 60,
          timeout: float = 20.0) -> list[dict]:
    host, tenant, site = split_slug(slug)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    out: list[dict] = []
    offset = 0
    with httpx.Client(timeout=timeout, headers={"Accept": "application/json"}) as client:
        while len(out) < max_jobs:
            resp = client.post(f"{base}/jobs", json={
                "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search,
            })
            resp.raise_for_status()
            postings = resp.json().get("jobPostings") or []
            if not postings:
                break
            for p in postings:
                if len(out) >= max_jobs:
                    break
                path = p.get("externalPath") or ""
                detail = client.get(f"{base}{path}")
                if detail.status_code != 200:
                    continue
                info = detail.json().get("jobPostingInfo") or {}
                remote_id = info.get("jobReqId") or info.get("id") or path.rsplit("/", 1)[-1]
                out.append({
                    "id": f"workday:{slug}:{remote_id}",
                    "source": "workday",
                    "source_company": slug,
                    "company_name": tenant.title(),
                    "title": info.get("title") or p.get("title", ""),
                    "location": info.get("location") or p.get("locationsText"),
                    "department": None,
                    "description": html_to_text(info.get("jobDescription")),
                    "url": info.get("externalUrl") or f"https://{host}/{site}{path}",
                    "posted_at": info.get("startDate") or _posted_on(p.get("postedOn")),
                })
            offset += 20
    return out


def _posted_on(text: str | None) -> str | None:
    """Turn Workday's 'Posted 3 Days Ago' into an ISO date."""
    if not text:
        return None
    now = datetime.now(timezone.utc)
    if "today" in text.lower():
        return now.date().isoformat()
    if "yesterday" in text.lower():
        return (now - timedelta(days=1)).date().isoformat()
    m = _POSTED_RE.search(text)
    if m:
        return (now - timedelta(days=int(m.group(1)))).date().isoformat()
    return None
