"""Gmail and Google Calendar access (optional: pip install 'jobsearch-cli[google]').

One-time setup per user:
1. console.cloud.google.com > new project > enable Gmail API and Google Calendar API.
2. OAuth consent screen: External, add yourself as a test user.
3. Credentials > Create OAuth client ID > Desktop app > download the JSON.
4. Save it as .secrets/google_credentials.json, then run `jobsearch email connect`.

The token is stored in .secrets/google_token.json (gitignored) and never leaves
your machine.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import parseaddr

from .config import SECRETS_DIR

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
]
CREDENTIALS = SECRETS_DIR / "google_credentials.json"
TOKEN = SECRETS_DIR / "google_token.json"


class GoogleNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return TOKEN.exists()


def _creds(interactive: bool = False):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise GoogleNotConfigured(
            "Google libraries missing. Run: pip install -e \".[google]\""
        ) from e
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactive:
        if not CREDENTIALS.exists():
            raise GoogleNotConfigured(f"Put your OAuth client JSON at {CREDENTIALS} first.")
        creds = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES).run_local_server(port=0)
    else:
        raise GoogleNotConfigured("Gmail not connected. Run `jobsearch email connect`.")
    SECRETS_DIR.mkdir(exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def connect() -> str:
    """Run the browser sign-in and return the connected address."""
    creds = _creds(interactive=True)
    return gmail(creds).users().getProfile(userId="me").execute()["emailAddress"]


def gmail(creds=None):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds or _creds(), cache_discovery=False)


def calendar(creds=None):
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds or _creds(), cache_discovery=False)


def _body_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts") or []:
        text = _body_text(part)
        if text:
            return text
    return ""


def recent_messages(service, days: int = 14, max_results: int = 200) -> list[dict]:
    query = f"newer_than:{days}d -in:sent -category:promotions -category:social"
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    out = []
    for m in resp.get("messages") or []:
        full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
        name, addr = parseaddr(headers.get("from", ""))
        out.append({
            "id": m["id"],
            "from_name": name,
            "from_email": addr.lower(),
            "subject": headers.get("subject", ""),
            "date": datetime.fromtimestamp(int(full["internalDate"]) / 1000).isoformat(timespec="seconds"),
            "snippet": full.get("snippet", ""),
            "body": _body_text(full["payload"])[:6000],
        })
    return out


def _raw(to: str, subject: str, body: str) -> str:
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft(service, to: str, subject: str, body: str) -> str:
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": _raw(to, subject, body)}}
    ).execute()
    return draft["id"]


def send(service, to: str, subject: str, body: str) -> str:
    return service.users().messages().send(
        userId="me", body={"raw": _raw(to, subject, body)}
    ).execute()["id"]


def create_event(service, summary: str, start: datetime, minutes: int, description: str,
                 timezone: str = "America/New_York") -> str:
    end = start + timedelta(minutes=minutes)
    event = service.events().insert(calendarId="primary", body={
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        "reminders": {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": 60}, {"method": "popup", "minutes": 1440}]},
    }).execute()
    return event["id"]
