"""Telegram bot: run your search from your phone.

Setup: message @BotFather, /newbot, copy the token into the TELEGRAM_BOT_TOKEN
env var, run `jobsearch bot`, then send /start to your bot. It replies with your
chat id; put that in config.yaml under telegram.chat_id. The bot ignores
everyone else.
"""
from __future__ import annotations

import time
from typing import Callable

import httpx

from . import db, keywords, notify, pipeline, stats
from .config import company_name

HELP = """Commands:
/today - new top matches, follow-ups, interviews
/list - top 10 open matches
/analyze <id> - what the job wants vs your resume
/status <id> <applied|interviewing|rejected|offer|withdrawn>
/followups - what's due
/stats - response and callback rates
/report - weekly summary"""


class Bot:
    def __init__(self, cfg: dict, log: Callable[[str], None] = print):
        self.cfg = cfg
        self.token = notify.telegram_token(cfg)
        if not self.token:
            raise notify.NotifyError("Set TELEGRAM_BOT_TOKEN (from @BotFather) first.")
        self.chat_id = str((cfg.get("telegram") or {}).get("chat_id") or "")
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.log = log

    def reply(self, chat: str, text: str) -> None:
        notify.telegram_send(self.cfg, text or "(nothing)", chat_id=chat)

    def send_file(self, chat: str, path) -> None:
        with open(path, "rb") as f:
            httpx.post(f"{self.api}/sendDocument", data={"chat_id": chat},
                       files={"document": (path.name, f)}, timeout=60)

    def handle(self, chat: str, text: str) -> None:
        if not self.chat_id:
            self.reply(chat, f"Your chat id is {chat}. Put it in config.yaml under telegram.chat_id "
                             "and restart `jobsearch bot`.")
            return
        if chat != self.chat_id:
            return
        cmd, *args = text.strip().split()
        cmd = cmd.split("@")[0].lower()
        if cmd in ("/start", "/help"):
            self.reply(chat, HELP)
        elif cmd == "/today":
            out, _ = pipeline.digest(self.cfg, only_new=False, mark=False)
            self.reply(chat, out or "Nothing new today.")
        elif cmd == "/list":
            out, _ = pipeline.digest(self.cfg, only_new=False, mark=False, limit=10)
            self.reply(chat, out or "No matches yet.")
        elif cmd == "/analyze" and args:
            with db.connect() as conn:
                job, track, _ = pipeline.job_and_track(conn, args[0])
            _, resume = pipeline.resume_for(self.cfg, track)
            a = keywords.analyze_job(job, resume, pipeline.extra_terms(self.cfg))
            lines = [f"{job['title']} at {company_name(job)}", f"Coverage: {a.coverage:.0%}", ""]
            lines += [f"{t.status}: {t.term} ({t.job_count}x) - {t.action}" for t in a.terms[:12]
                      if t.status != "GOOD"]
            self.reply(chat, "\n".join(lines))
        elif cmd == "/status" and len(args) >= 2:
            if args[1] not in ("drafted", "applied", "interviewing", "rejected", "offer", "withdrawn"):
                self.reply(chat, "Status must be applied, interviewing, rejected, offer, or withdrawn.")
                return
            with db.connect() as conn:
                db.update_application(conn, args[0], args[1],
                                      followup_days=self.cfg.get("followup_days") or {})
            self.reply(chat, f"{args[0]} is now {args[1]}")
        elif cmd == "/followups":
            from .cli import due_followups

            with db.connect() as conn:
                due = due_followups(conn)
            self.reply(chat, "\n".join(f"{d['title']} at {company_name(d)} ({d['status']})"
                                       for d in due) or "Nothing due.")
        elif cmd == "/stats":
            with db.connect() as conn:
                o = stats.funnel(conn)["overall"].get("all")
            self.reply(chat, f"Applied {o.applied}, responses {o.response_rate:.0%}, "
                             f"callbacks {o.callback_rate:.0%}" if o else "No applications yet.")
        elif cmd == "/report":
            with db.connect() as conn:
                self.reply(chat, stats.weekly(conn))
        else:
            self.reply(chat, HELP)

    def run(self) -> None:
        offset = 0
        self.log("Bot running. Ctrl+C to stop.")
        while True:
            try:
                r = httpx.get(f"{self.api}/getUpdates", params={"timeout": 50, "offset": offset}, timeout=60)
                updates = r.json().get("result", [])
            except httpx.HTTPError:
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                text = msg.get("text")
                if not text:
                    continue
                chat = str(msg["chat"]["id"])
                try:
                    self.handle(chat, text)
                except Exception as e:  # noqa: BLE001
                    self.log(f"error handling {text!r}: {e}")
                    if chat == self.chat_id:
                        self.reply(chat, f"Error: {e}")
