"""Send a message to you: Gmail, plain SMTP, or Telegram, per config `notify:`.

notify:
  channel: telegram        # telegram | gmail | smtp | none
  email_to: you@gmail.com  # for gmail/smtp
  smtp: {host: smtp.gmail.com, port: 587, user: you@gmail.com, password_env: JOBSEARCH_SMTP_PASSWORD}
telegram:
  bot_token_env: TELEGRAM_BOT_TOKEN
  chat_id: "123456789"
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

import httpx


class NotifyError(RuntimeError):
    pass


def telegram_token(cfg: dict) -> str | None:
    t = cfg.get("telegram") or {}
    return os.environ.get(t.get("bot_token_env") or "TELEGRAM_BOT_TOKEN") or t.get("bot_token")


def telegram_send(cfg: dict, text: str, chat_id: str | None = None) -> None:
    token = telegram_token(cfg)
    chat = chat_id or str((cfg.get("telegram") or {}).get("chat_id") or "")
    if not token or not chat:
        raise NotifyError("Telegram needs a bot token and chat_id (see `jobsearch bot --help`).")
    for i in range(0, len(text), 3900):
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat, "text": text[i:i + 3900],
                             "disable_web_page_preview": True}, timeout=15)
        if r.status_code != 200:
            raise NotifyError(f"Telegram error {r.status_code}: {r.text[:200]}")


def send(cfg: dict, subject: str, body: str) -> str:
    """Deliver via the configured channel. Returns the channel used."""
    n = cfg.get("notify") or {}
    channel = n.get("channel") or "none"
    if channel == "telegram":
        telegram_send(cfg, f"{subject}\n\n{body}")
    elif channel == "gmail":
        from . import google_api

        to = n.get("email_to") or ""
        if not to:
            raise NotifyError("notify.email_to is not set.")
        google_api.send(google_api.gmail(), to, subject, body)
    elif channel == "smtp":
        s = n.get("smtp") or {}
        password = os.environ.get(s.get("password_env") or "JOBSEARCH_SMTP_PASSWORD")
        if not (s.get("host") and s.get("user") and password and n.get("email_to")):
            raise NotifyError("SMTP needs notify.smtp.host/user, notify.email_to, and the password env var.")
        msg = MIMEText(body)
        msg["Subject"], msg["From"], msg["To"] = subject, s["user"], n["email_to"]
        with smtplib.SMTP(s["host"], int(s.get("port") or 587), timeout=20) as smtp:
            smtp.starttls()
            smtp.login(s["user"], password)
            smtp.send_message(msg)
    return channel
