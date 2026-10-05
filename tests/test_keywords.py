from jobsearch import keywords


def _by_term(analysis):
    return {t.term: t for t in analysis.terms}


def test_analyze_flags_buried_wording_missing_and_good(job, resume_text):
    a = keywords.analyze_job(job, resume_text)
    terms = _by_term(a)
    assert terms["SQL"].status == "GOOD"
    assert terms["Tableau"].status == "BURIED"          # only in the skills list
    assert terms["Tableau"].importance == "required"
    assert terms["Dashboards"].status == "WORDING"      # resume says "reports"
    assert terms["Snowflake"].status == "MISSING"
    assert terms["dbt"].status == "NICE-TO-HAVE"
    assert ("dashboards", "reports") in a.wording
    assert a.salary == (75000, 95000)
    assert 0 < a.coverage < 1


def test_terms_ranked_by_weight_with_required_first(job, resume_text):
    a = keywords.analyze_job(job, resume_text)
    weights = [t.weight for t in a.terms]
    assert weights == sorted(weights, reverse=True)
    assert a.terms[0].importance == "required"


def test_aliases_count_as_one_skill():
    skill = next(s for s in keywords.all_skills() if s.name == "Power BI")
    assert skill.count("PowerBI and Power BI Desktop") == 2


def test_short_aliases_respect_word_boundaries():
    skills = {s.name: s for s in keywords.all_skills()}
    assert skills["Excel"].count("excellent communicator") == 0
    assert skills["C#"].count("We use C# and .NET") >= 1


def test_extra_terms_are_analyzed(job, resume_text):
    a = keywords.analyze_job({**job, "description": job["description"] + "\nRequirements\n- Epic EHR"},
                             resume_text, extra_terms=["Epic EHR"])
    assert "Epic EHR" in {t.term for t in a.terms}


def test_market_terms_and_cloud(job, resume_text):
    other = {"title": "BI Analyst", "description": "Requirements\n- Tableau dashboards\n- SQL"}
    terms, _ = keywords.market_terms([job, other], resume_text)
    by = {t.term: t for t in terms}
    assert by["Tableau"].jobs_mentioning == 2
    assert by["SQL"].on_resume
    html = keywords.cloud_html(terms, [], 2)
    assert "Tableau" in html and "<!doctype html>" in html
