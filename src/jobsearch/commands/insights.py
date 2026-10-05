"""What's working: funnel stats and the weekly report."""
from __future__ import annotations

import click
from rich.table import Table

from .. import db, notify, stats
from ..config import console, load_config


@click.command(name="stats")
def stats_cmd() -> None:
    """Response and callback rates by resume track, tailoring, source, and timing."""
    with db.connect() as conn:
        groups = stats.funnel(conn)
    if not groups["overall"]:
        console.print("[yellow]No applications logged yet. Mark them with `track --status applied`.[/yellow]")
        return
    for name, buckets in groups.items():
        table = Table(title=name.title())
        for col in ("Group", "Applied", "Responses", "Response rate", "Callbacks", "Callback rate"):
            table.add_column(col, justify="right" if col != "Group" else "left")
        for key, b in sorted(buckets.items(), key=lambda kv: -kv[1].applied):
            table.add_row(key, str(b.applied), str(b.responded), f"{b.response_rate:.0%}",
                          str(b.callbacks), f"{b.callback_rate:.0%}")
        console.print(table)
    console.print("[dim]Callback = reached interviewing or offer. Small samples are noisy; "
                  "trust trends after ~20 applications per group.[/dim]")


@click.command()
@click.option("--days", default=7, type=int)
@click.option("--send", is_flag=True, help="Send via your notify channel.")
def report(days: int, send: bool) -> None:
    """Weekly summary: what you did, what came back, what to do next."""
    cfg = load_config()
    target = int((cfg.get("search") or {}).get("weekly_target", 10))
    with db.connect() as conn:
        text = stats.weekly(conn, days=days, target=target)
    if send:
        channel = notify.send(cfg, f"Job search report ({days} days)", text)
        console.print(f"[green]Sent via {channel}.[/green]")
    else:
        console.print(text)


COMMANDS = [stats_cmd, report]
