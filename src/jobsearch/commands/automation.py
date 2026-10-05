"""Hands-off mode: daily run, scheduler, dashboard, Telegram bot."""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import click

from .. import automation, notify
from ..config import console, load_config


@click.command()
@click.option("--alerts", is_flag=True, help="Quick mode for hourly runs: only ping on strong new matches.")
def daily(alerts: bool) -> None:
    """Discover, score, sync email, draft follow-ups/thank-yous, send the digest."""
    text = automation.run_daily(load_config(), log=console.print, alerts_only=alerts)
    if text:
        console.print("\n" + text)


@click.group()
def schedule() -> None:
    """Run `jobsearch daily` automatically (Windows Task Scheduler or cron)."""


@schedule.command(name="install")
@click.option("--at", default="07:30", help="Daily run time, HH:MM.")
@click.option("--hourly-alerts", is_flag=True, help="Also check hourly and ping on strong new matches.")
def schedule_install(at: str, hourly_alerts: bool) -> None:
    load_config()
    try:
        done = automation.install_schedule(Path.cwd(), at, hourly_alerts)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Couldn't install the schedule: {e}[/red]")
        sys.exit(1)
    for d in done:
        console.print(f"[green]Installed:[/green] {d}")
    console.print("Logs go to ./logs/. Set notify.channel in config.yaml so the digest reaches you.")


@schedule.command(name="remove")
def schedule_remove() -> None:
    for d in automation.remove_schedule() or ["Nothing to remove"]:
        console.print(d)


@click.command()
@click.option("--port", default=8765, type=int)
@click.option("--no-open", is_flag=True)
def dashboard(port: int, no_open: bool) -> None:
    """Local drag-and-drop board of your pipeline."""
    from .. import dashboard as dash

    cfg = load_config()
    server = dash.serve(port, cfg.get("followup_days") or {})
    url = f"http://127.0.0.1:{port}"
    console.print(f"[green]Dashboard at {url}[/green]  (Ctrl+C to stop)")
    if not no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


@click.command()
def bot() -> None:
    """Telegram bot: /today, /apply <id>, /status, /stats from your phone.

    \b
    1. In Telegram, message @BotFather, send /newbot, copy the token
    2. Set the TELEGRAM_BOT_TOKEN environment variable to it
    3. Run `jobsearch bot` and send /start to your bot
    4. Put the chat id it replies with in config.yaml under telegram.chat_id
    """
    from ..bot import Bot

    try:
        Bot(load_config(), log=console.print).run()
    except notify.NotifyError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("Stopped.")


COMMANDS = [daily, schedule, dashboard, bot]
