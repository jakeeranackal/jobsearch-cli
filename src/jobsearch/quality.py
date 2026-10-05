"""Freshness, duplicates, salary, and red flags for discovered jobs."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from . import jd

STALE_DAYS = 45
# States/cities with pay-range posting laws. A posting there without a range is a yellow flag.
PAY_TRANSPARENCY = {
    "CA": "California", "CO": "Colorado", "WA": "Washington", "NY": "New York",
    "IL": "Illinois", "MD": "Maryland", "MN": "Minnesota", "HI": "Hawaii",
    "DC": "District of Columbia", "NJ": "New Jersey", "VT": "Vermont", "MA": "Massachusetts",
}
_STAFFING = re.compile(r"\b(staffing|recruiting firm|recruitment agency|talent solutions|our client)\b", re.I)
_SUFFIX = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|group|holdings|plc)\b\.?", re.I)


def norm(s: str | None) -> str:
    s = _SUFFIX.sub("", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            d = parsedate_to_datetime(str(s))
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def age_days(job: dict) -> int | None:
    d = _parse_date(job.get("posted_at")) or _parse_date(job.get("discovered_at"))
    if not d:
        return None
    return max(0, (datetime.now(timezone.utc) - d).days)


def flags(job: dict) -> list[str]:
    out = []
    company = job.get("company_name") or job.get("source_company") or ""
    if _STAFFING.search(company) or _STAFFING.search((job.get("description") or "")[:1500]):
        out.append("staffing agency")
    age = age_days(job)
    if age is not None and age > STALE_DAYS:
        out.append(f"open {age}d")
    loc = job.get("location") or ""
    if not (job.get("salary_min") or jd.extract_salary(job.get("description") or "")):
        for code, name in PAY_TRANSPARENCY.items():
            if re.search(rf"\b{code}\b", loc) or name.lower() in loc.lower():
                out.append(f"no salary ({code} requires one)")
                break
    return out


def refresh(conn: sqlite3.Connection) -> dict[str, int]:
    """Recompute salary, flags and duplicates for every open job."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE is_open = 1 ORDER BY discovered_at")]
    seen: dict[tuple, str] = {}
    counts = {"salary": 0, "flagged": 0, "duplicates": 0}
    for job in rows:
        if not job.get("salary_min"):
            sal = jd.extract_salary(job.get("description") or "")
            if sal:
                job["salary_min"], job["salary_max"] = sal
                counts["salary"] += 1
        f = flags(job)
        counts["flagged"] += bool(f)
        key = (norm(job.get("company_name") or job["source_company"]), norm(job["title"]),
               norm(job.get("location")))
        dup_of = seen.get(key)
        if dup_of:
            counts["duplicates"] += 1
        else:
            seen[key] = job["id"]
        conn.execute(
            "UPDATE jobs SET salary_min = ?, salary_max = ?, flags = ?, dup_of = ? WHERE id = ?",
            (job.get("salary_min"), job.get("salary_max"), ", ".join(f) or None, dup_of, job["id"]),
        )
    return counts
