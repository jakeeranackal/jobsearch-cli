"""The unattended daily run, and installing it on a schedule."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import db, google_api, inbox, notify, pipeline, stats

Log = Callable[[str], None]
TASK_DAILY = "jobsearch-daily"
TASK_ALERTS = "jobsearch-alerts"


def run_daily(cfg: dict, log: Log = print, alerts_only: bool = False) -> str:
    """Discover, score, sync email statuses, and send the digest."""
    log(f"[bold]jobsearch daily: {datetime.now():%Y-%m-%d %H:%M}[/bold]")
    pipeline.discover(cfg, log=log)
    pipeline.match(cfg, log=log)

    if alerts_only:
        threshold = (cfg.get("alerts") or {}).get("min_score", 0.35)
        text, n = pipeline.digest(cfg, only_new=True, min_score=threshold, limit=5)
        if n and (cfg.get("notify") or {}).get("channel", "none") != "none":
            notify.send(cfg, f"New strong match{'es' if n > 1 else ''} ({n})", text)
        return text

    if google_api.is_configured():
        try:
            msgs = google_api.recent_messages(google_api.gmail(), days=3)
            with db.connect() as conn:
                events = inbox.sync(conn, msgs, cfg.get("followup_days") or {})
            for e in events:
                if e["change"]:
                    log(f"  Email: {e['company']} {e['change'][0]} to {e['change'][1]}")
        except Exception as e:  # noqa: BLE001
            log(f"  [yellow]Email sync skipped: {e}[/yellow]")

    text, n = pipeline.digest(cfg, only_new=True)
    report_day = (cfg.get("digest") or {}).get("weekly_report_day", "monday").lower()
    if datetime.now().strftime("%A").lower() == report_day:
        with db.connect() as conn:
            text += "\n\n" + stats.weekly(conn, target=int((cfg.get("search") or {}).get("weekly_target", 10)))
    channel = (cfg.get("notify") or {}).get("channel", "none")
    if channel != "none" and text:
        notify.send(cfg, f"Job digest: {n} new match(es)", text)
        log(f"  Digest sent via {channel}")
    return text


def _runner(project: Path, args: str) -> Path:
    """Write a small launcher so the scheduler runs in the project folder with the right Python."""
    logs = project / "logs"
    logs.mkdir(exist_ok=True)
    py = sys.executable
    if platform.system() == "Windows":
        name = "alerts" if "alerts" in args else "daily"
        path = project / f"run_{name}.cmd"
        path.write_text(f'@echo off\r\ncd /d "{project}"\r\n"{py}" -m jobsearch daily {args} '
                        f'>> "logs\\{name}.log" 2>&1\r\n', encoding="utf-8")
    else:
        name = "alerts" if "alerts" in args else "daily"
        path = project / f"run_{name}.sh"
        path.write_text(f'#!/bin/sh\ncd "{project}"\n"{py}" -m jobsearch daily {args} >> logs/{name}.log 2>&1\n',
                        encoding="utf-8")
        path.chmod(0o755)
    return path


def install_schedule(project: Path, at: str = "07:30", hourly_alerts: bool = False) -> list[str]:
    done = []
    daily = _runner(project, "")
    if platform.system() == "Windows":
        subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", TASK_DAILY,
                        "/TR", f'"{daily}"', "/ST", at], check=True, capture_output=True)
        done.append(f"Windows Task '{TASK_DAILY}' daily at {at}")
        if hourly_alerts:
            alerts = _runner(project, "--alerts")
            subprocess.run(["schtasks", "/Create", "/F", "/SC", "HOURLY", "/TN", TASK_ALERTS,
                            "/TR", f'"{alerts}"'], check=True, capture_output=True)
            done.append(f"Windows Task '{TASK_ALERTS}' every hour")
        return done
    if not shutil.which("crontab"):
        raise RuntimeError("crontab not found; add the run_daily.sh script to your scheduler manually.")
    hh, mm = at.split(":")
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    keep = [ln for ln in current.splitlines() if "jobsearch" not in ln]
    keep.append(f"{int(mm)} {int(hh)} * * * {daily}")
    if hourly_alerts:
        keep.append(f"5 * * * * {_runner(project, '--alerts')}")
    subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n", text=True, check=True)
    done.append(f"cron daily at {at}" + (" + hourly alerts" if hourly_alerts else ""))
    return done


def remove_schedule() -> list[str]:
    done = []
    if platform.system() == "Windows":
        for task in (TASK_DAILY, TASK_ALERTS):
            r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", task], capture_output=True)
            if r.returncode == 0:
                done.append(f"Removed {task}")
        return done
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    keep = [ln for ln in current.splitlines() if "jobsearch" not in ln]
    subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n", text=True, check=True)
    return ["Removed jobsearch cron entries"]

