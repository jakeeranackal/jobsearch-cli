"""Local pipeline board at http://127.0.0.1:8765. Reads and writes the same SQLite DB.

Standard library only. Bound to localhost; there is no auth, so don't expose it.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db, quality, stats
from .config import company_name

HTML = Path(__file__).parent / "data" / "dashboard.html"
STATUSES = ("drafted", "applied", "interviewing", "offer", "rejected", "withdrawn")


def board(min_score: float = 0.2, matches: int = 40) -> dict:
    with db.connect() as conn:
        apps = [dict(r) for r in conn.execute(
            """SELECT a.job_id, a.status, a.last_update_at, a.next_followup_at, j.title, j.url,
                      j.source_company, j.company_name, j.location, j.salary_min, j.salary_max,
                      j.posted_at, j.discovered_at, j.flags,
                      (SELECT MAX(score) FROM scores s WHERE s.job_id = j.id) score
               FROM applications a JOIN jobs j ON j.id = a.job_id
               ORDER BY a.last_update_at DESC""")]
        top = [dict(r) for r in conn.execute(
            """SELECT j.id job_id, j.title, j.url, j.source_company, j.company_name, j.location,
                      j.salary_min, j.salary_max, j.posted_at, j.discovered_at, j.flags, MAX(s.score) score
               FROM jobs j JOIN scores s ON s.job_id = j.id
               WHERE j.is_open = 1 AND j.dup_of IS NULL
                 AND j.id NOT IN (SELECT job_id FROM applications)
               GROUP BY j.id HAVING score >= ? ORDER BY score DESC LIMIT ?""", (min_score, matches))]
        overall = stats.funnel(conn)["overall"].get("all")

    def card(r: dict) -> dict:
        return {
            "id": r["job_id"], "title": r["title"], "company": company_name(r), "url": r["url"],
            "location": r.get("location") or "", "score": round(r.get("score") or 0, 2),
            "age": quality.age_days(r), "flags": r.get("flags") or "",
            "salary": (f"${r['salary_min'] // 1000}k-${(r['salary_max'] or r['salary_min']) // 1000}k"
                       if r.get("salary_min") else ""),
            "followup": (r.get("next_followup_at") or "")[:10],
        }

    columns = {"matches": [card(r) for r in top]}
    for s in ("drafted", "applied", "interviewing", "offer"):
        columns[s] = [card(r) for r in apps if r["status"] == s]
    columns["closed"] = [card(r) | {"status": r["status"]} for r in apps
                         if r["status"] in ("rejected", "withdrawn")]
    summary = {"applied": overall.applied if overall else 0,
               "response_rate": round(overall.response_rate, 3) if overall else 0,
               "callback_rate": round(overall.callback_rate, 3) if overall else 0}
    return {"columns": columns, "stats": summary}


def make_handler(followup_days: dict):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif self.path.startswith("/api/board"):
                self._send(200, json.dumps(board()).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def _local_request(self) -> bool:
            # JSON content type forces a CORS preflight (which we never answer), so other
            # websites can't post here; the Host check blocks DNS rebinding.
            host = (self.headers.get("Host") or "").split(":")[0]
            ctype = self.headers.get("Content-Type") or ""
            return host in ("127.0.0.1", "localhost") and ctype.startswith("application/json")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/status":
                self._send(404, b"not found", "text/plain")
                return
            if not self._local_request():
                self._send(403, b'{"error":"forbidden"}', "application/json")
                return
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                job_id, status = str(data["job_id"]), str(data["status"])
            except (ValueError, KeyError):
                self._send(400, b'{"error":"bad request"}', "application/json")
                return
            if status not in STATUSES:
                self._send(400, b'{"error":"bad status"}', "application/json")
                return
            with db.connect() as conn:
                if not db.get_job(conn, job_id):
                    self._send(404, b'{"error":"no such job"}', "application/json")
                    return
                db.update_application(conn, job_id, status, followup_days=followup_days)
            self._send(200, b'{"ok":true}', "application/json")

        def log_message(self, *args) -> None:
            pass

    return Handler


def serve(port: int, followup_days: dict) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(followup_days))
