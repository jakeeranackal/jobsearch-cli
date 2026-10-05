from jobsearch import llm, tailor


def test_reorder_puts_most_relevant_bullet_first(job, resume_text):
    r = tailor.tailor(job, resume_text, {}, use_ai=False)
    exp = r.resume.section("experience")
    bullets = [i.text for i in exp.items if i.kind == "bullet"]
    assert bullets[0].startswith("Wrote SQL")
    assert not r.used_ai
    assert any("Tableau" in t for t in r.todo)


def test_skills_reordered_by_job_weight(job, resume_text):
    r = tailor.tailor(job, resume_text, {}, use_ai=False)
    skills = r.resume.section("skills").items[0].text
    assert skills.index("Tableau") < skills.index("Excel")


def test_max_bullets_trims(job, resume_text):
    r = tailor.tailor(job, resume_text, {}, use_ai=False, max_bullets=1)
    exp = r.resume.section("experience")
    assert sum(1 for i in exp.items if i.kind == "bullet") == 2  # one per role


def test_fabrication_check_catches_new_tools_and_numbers(resume_text):
    fake = resume_text + "\n- Built Snowflake pipelines saving 40%"
    warnings = tailor.fabrication_check(resume_text, fake)
    joined = " ".join(warnings)
    assert "Snowflake" in joined and "40%" in joined


def test_ai_path_uses_model_output_and_runs_guard(job, resume_text, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda cfg=None: True)
    captured = {}

    def fake_ask_json(cfg, system, prompt, schema, **kw):
        captured["prompt"] = prompt
        return {
            "sections": [
                {"title": "Experience", "items": [
                    {"kind": "heading", "text": "Data Analyst, Numoda Corp, 2023 - Present"},
                    {"kind": "bullet", "text": "Built Tableau dashboards in Snowflake for clinical ops"},
                ]},
                {"title": "Skills", "items": [{"kind": "text", "text": "SQL, Tableau, Python"}]},
            ],
            "changes": ["Led with dashboard work"],
            "gaps": ["dbt"],
        }

    monkeypatch.setattr(llm, "ask_json", fake_ask_json)
    r = tailor.tailor(job, resume_text, {"llm": {}}, use_ai=True)
    assert r.used_ai
    assert "MASTER RESUME" in captured["prompt"]
    assert r.resume.header[0] == "Jordan Lee"
    assert any("Snowflake" in w for w in r.warnings)
    assert r.todo == ["Not supported by your resume: dbt"]
