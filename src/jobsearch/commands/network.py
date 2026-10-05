"""Your network: import LinkedIn connections, find referrals."""
from __future__ import annotations

import click
from rich.table import Table

from .. import db, network as net
from ..config import company_name, console


@click.group(name="network")
def network_group() -> None:
    """LinkedIn connections and referral matching."""


@network_group.command(name="import")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
def network_import(csv_path: str) -> None:
    """Import Connections.csv from LinkedIn's data export.

    \b
    LinkedIn > Settings & Privacy > Data privacy > Get a copy of your data >
    pick "Connections" > Request archive. The email arrives in ~10 minutes.
    """
    with db.connect() as conn:
        n = net.import_linkedin_csv(conn, csv_path)
    console.print(f"[green]Imported {n} connections.[/green] Run `jobsearch referrals` to see who can help.")


@click.command()
@click.option("--min-score", default=0.2, type=float)
def referrals(min_score: float) -> None:
    """Your top-matching open jobs where you know someone at the company."""
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM connections LIMIT 1").fetchone():
            console.print("[yellow]No connections imported. Run `jobsearch network import <Connections.csv>`.[/yellow]")
            return
        jobs = [dict(r) for r in conn.execute(
            """SELECT j.*, MAX(s.score) score FROM jobs j JOIN scores s ON s.job_id = j.id
               WHERE j.is_open = 1 AND j.dup_of IS NULL GROUP BY j.id HAVING score >= ?
               ORDER BY score DESC""", (min_score,))]
        cache: dict[str, list[dict]] = {}
        table = Table(title="Jobs where you have a way in")
        for col in ("Score", "Role", "Company", "You know", "ID"):
            table.add_column(col)
        hits = 0
        for j in jobs:
            comp = company_name(j)
            people = cache.setdefault(comp, net.referrals(conn, comp))
            if people:
                hits += 1
                names = ", ".join(f"{p['name']} ({p['position'] or '?'})" for p in people[:3])
                table.add_row(f"{j['score']:.2f}", j["title"], comp, names, j["id"])
    if hits:
        console.print(table)
        console.print("Next: `jobsearch contacts <id>` for links, then ask Claude to write the referral ask.")
    else:
        console.print("No matches between your connections and current top jobs.")


COMMANDS = [network_group, referrals]
