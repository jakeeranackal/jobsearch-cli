import httpx

from jobsearch.sources import base, manual, smartrecruiters, workable, workday


def test_html_to_text_keeps_structure():
    html = "<h3>Requirements</h3><ul><li>SQL</li><li>Tableau &amp; Excel</li></ul><p>Benefits</p>"
    text = base.html_to_text(html)
    lines = [ln for ln in text.splitlines() if ln]
    assert lines[:3] == ["Requirements", "- SQL", "- Tableau & Excel"]


def test_html_to_text_handles_greenhouse_double_escaping():
    assert "- SQL" in base.html_to_text("&lt;ul&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;")


def test_detect_ats_urls():
    assert manual.detect_ats("https://boards.greenhouse.io/airbnb/jobs/123") == ("greenhouse", "airbnb", "123")
    assert manual.detect_ats("https://job-boards.greenhouse.io/notion") == ("greenhouse", "notion", None)
    assert manual.detect_ats("https://jobs.lever.co/netflix")[0:2] == ("lever", "netflix")
    assert manual.detect_ats("https://jobs.ashbyhq.com/openai")[0:2] == ("ashby", "openai")
    assert manual.detect_ats("https://apply.workable.com/acme/")[0:2] == ("workable", "acme")
    assert manual.detect_ats("https://jobs.smartrecruiters.com/Visa")[0:2] == ("smartrecruiters", "Visa")
    assert manual.detect_ats("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite") == (
        "workday", "nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", None)
    assert manual.detect_ats("https://example.com/careers") is None
    assert manual.is_blocked("https://www.linkedin.com/jobs/view/1")


def test_workday_slug_and_posted_on():
    assert workday.split_slug("https://acme.wd1.myworkdayjobs.com/en-US/Careers/") == (
        "acme.wd1.myworkdayjobs.com", "acme", "Careers")
    assert workday._posted_on("Posted 3 Days Ago") is not None
    assert workday._posted_on("Posted 30+ Days Ago") is not None


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def test_workable_normalizes(monkeypatch):
    data = {"name": "Acme", "jobs": [{
        "title": "Analyst", "shortcode": "AB12", "city": "Philadelphia", "state": "PA",
        "country": "US", "telecommuting": True, "description": "<p>SQL</p>",
        "url": "https://apply.workable.com/acme/j/AB12", "published_on": "2026-10-01"}]}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(data))
    [job] = workable.fetch("acme")
    assert job["id"] == "workable:acme:AB12"
    assert job["location"] == "Philadelphia, PA, US (Remote)"
    assert job["company_name"] == "Acme"
    assert job["description"] == "SQL"


def test_smartrecruiters_normalizes():
    posting = {"id": "99", "name": "Data Analyst", "releasedDate": "2026-10-01",
               "location": {"city": "Austin", "region": "TX", "country": "us"},
               "company": {"name": "Visa"}, "department": {"label": "Analytics"}}
    detail = {"postingUrl": "https://jobs.smartrecruiters.com/Visa/99", "jobAd": {"sections": {
        "jobDescription": {"title": "Job Description", "text": "<p>Build dashboards</p>"},
        "qualifications": {"title": "Qualifications", "text": "<ul><li>SQL</li></ul>"}}}}
    job = smartrecruiters._normalize("Visa", posting, detail)
    assert job["id"] == "smartrecruiters:Visa:99"
    assert "Qualifications\n- SQL" in job["description"]
    assert job["location"] == "Austin, TX, us"


def test_from_text_builds_stable_id():
    a = manual.from_text("desc", title="Analyst", company="Acme Health")
    b = manual.from_text("desc", title="Analyst", company="Acme Health")
    assert a["id"] == b["id"] and a["id"].startswith("manual:acme-health:")
