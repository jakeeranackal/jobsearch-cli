from jobsearch import tailor


def test_reorder_puts_most_relevant_bullet_first(job, resume_text):
    r = tailor.tailor(job, resume_text)
    exp = r.resume.section("experience")
    bullets = [i.text for i in exp.items if i.kind == "bullet"]
    assert bullets[0].startswith("Wrote SQL")
    assert any("Tableau" in t for t in r.todo)


def test_skills_reordered_by_job_weight(job, resume_text):
    r = tailor.tailor(job, resume_text)
    skills = r.resume.section("skills").items[0].text
    assert skills.index("Tableau") < skills.index("Excel")


def test_max_bullets_trims(job, resume_text):
    r = tailor.tailor(job, resume_text, max_bullets=1)
    exp = r.resume.section("experience")
    assert sum(1 for i in exp.items if i.kind == "bullet") == 2  # one per role


def test_fabrication_check_catches_new_tools_and_numbers(resume_text):
    fake = resume_text + "\n- Built Snowflake pipelines saving 40%"
    joined = " ".join(tailor.fabrication_check(resume_text, fake))
    assert "Snowflake" in joined and "40%" in joined


def test_check_scores_an_honest_edit(job, resume_text):
    edited = resume_text.replace(
        "Built Excel reports used by 3 business partners",
        "Built Tableau dashboards used by 3 stakeholders")
    r = tailor.check(job, resume_text, edited)
    assert r.warnings == []
    assert r.coverage_after > r.coverage_before


def test_check_flags_an_invented_claim(job, resume_text):
    r = tailor.check(job, resume_text, resume_text + "\n- Migrated warehouse to Snowflake")
    assert any("Snowflake" in w for w in r.warnings)
