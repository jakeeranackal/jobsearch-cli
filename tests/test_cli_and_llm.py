import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from jobsearch import dashboard, db, llm
from jobsearch.cli import cli


def _run(*args, input=None):
    result = CliRunner().invoke(cli, list(args), input=input, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def test_add_analyze_apply_flow(project, jd_text):
    (project / "listing.txt").write_text(jd_text, encoding="utf-8")
    out = _run("add", "--file", "listing.txt", "--title", "Data Analyst", "--company", "Acme Health")
    assert "Added" in out
    with db.connect() as conn:
        job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
        assert conn.execute("SELECT salary_min FROM jobs").fetchone()[0] == 75000

    out = _run("analyze", job_id)
    assert "BURIED" in out and "Tableau" in out

    _run("apply", job_id, "--no-ai", "--no-open", "--applied")
    folder = next((project / "applications").iterdir())
    names = {p.name for p in folder.iterdir()}
    assert {"analysis.md", "cover_letter.md", "tailor_notes.md"} <= names
    assert any(n.endswith(".docx") for n in names)
    with db.connect() as conn:
        app = db.get_application(conn, job_id)
    assert app["status"] == "applied" and app["resume_path"]

    assert "Applications sent: 1" in _run("report")
    assert "Data Analyst" in _run("digest", "--all")


def test_dashboard_api(project, job):
    with db.connect() as conn:
        db.upsert_job(conn, job)
        db.record_score(conn, job["id"], "data", 0.5)
    srv = dashboard.serve(0, {"applied": 7})
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        board = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/board"))
        assert board["columns"]["matches"][0]["id"] == job["id"]
        body = json.dumps({"job_id": job["id"], "status": "applied"}).encode()
        plain = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", data=body,
                                       headers={"Content-Type": "text/plain"})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(plain)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", data=body,
                                     headers={"Content-Type": "application/json"})
        assert json.load(urllib.request.urlopen(req))["ok"]
        board = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/board"))
        assert board["columns"]["applied"][0]["id"] == job["id"]
    finally:
        srv.shutdown()


class _FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _fake_client(monkeypatch, response):
    messages = _FakeMessages(response)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    monkeypatch.setattr(llm, "_client", lambda: client)
    return messages


def test_llm_request_shape(monkeypatch):
    resp = SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text='{"a": 1}')])
    messages = _fake_client(monkeypatch, resp)
    assert llm.ask_json({"llm": {"effort": "low"}}, "sys", "hi", {"type": "object"}) == {"a": 1}
    kw = messages.kwargs
    assert kw["model"] == llm.DEFAULT_MODEL
    assert kw["fallbacks"] == "default" and llm.FALLBACK_BETA in kw["betas"]
    assert kw["output_config"]["effort"] == "low"
    assert kw["output_config"]["format"]["type"] == "json_schema"


def test_llm_refusal_raises(monkeypatch):
    _fake_client(monkeypatch, SimpleNamespace(stop_reason="refusal", content=[]))
    with pytest.raises(llm.LLMError):
        llm.ask_text({}, "sys", "hi")


def test_llm_disabled_by_config():
    assert llm.available({"llm": {"enabled": False}}) is False
