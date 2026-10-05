"""Your network: LinkedIn connections import, referral matches, people-search links.

LinkedIn can't be scraped, but it lets you export your own connections:
Settings > Data privacy > Get a copy of your data > Connections. That CSV is
what `jobsearch network import` reads.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus

from .quality import norm


def import_linkedin_csv(conn: sqlite3.Connection, path: str | Path) -> int:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    # The export starts with a few "Notes:" lines before the real header.
    start = next((i for i, ln in enumerate(lines) if ln.startswith("First Name")), 0)
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    conn.execute("DELETE FROM connections")
    n = 0
    for row in reader:
        name = f"{row.get('First Name', '').strip()} {row.get('Last Name', '').strip()}".strip()
        if not name:
            continue
        conn.execute(
            "INSERT INTO connections (name, company, position, email, url, connected_on) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, row.get("Company"), row.get("Position"), row.get("Email Address"),
             row.get("URL"), row.get("Connected On")),
        )
        n += 1
    return n


def referrals(conn: sqlite3.Connection, company: str) -> list[dict]:
    target = norm(company)
    if not target:
        return []
    out = []
    for r in conn.execute("SELECT * FROM connections WHERE company IS NOT NULL"):
        theirs = norm(r["company"])
        if not theirs:
            continue
        if theirs == target or (len(target) >= 4 and (target in theirs.split(" ") or
                                                      theirs.startswith(target + " "))):
            out.append(dict(r))
    return out


def people_search_links(company: str, title: str) -> dict[str, str]:
    team = title.split(",")[0]
    li = "https://www.linkedin.com/search/results/people/?keywords="
    g = "https://www.google.com/search?q="
    return {
        "Recruiters (LinkedIn)": li + quote_plus(f"{company} recruiter"),
        "Likely hiring manager (LinkedIn)": li + quote_plus(f"{company} {team} manager"),
        "Team members (LinkedIn)": li + quote_plus(f"{company} {team}"),
        "Recruiters (Google)": g + quote_plus(f'site:linkedin.com/in "{company}" recruiter'),
    }
