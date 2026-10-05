from jobsearch import jd


def test_sections_split_requirements_preferred_and_ignore_benefits(jd_text):
    p = jd.parse(jd_text)
    assert "Advanced SQL and Tableau" in p.text(jd.REQUIRED)
    assert "Python (pandas)" in p.text(jd.PREFERRED)
    assert "Tableau dashboards" in p.text(jd.RESPONSIBILITIES)
    assert "401k" not in p.relevant_text
    assert "equal opportunity" not in p.relevant_text.lower()


def test_single_line_description_still_splits():
    flat = ("We build tools. Requirements: 3+ years SQL, Tableau. Nice to have: Python. "
            "Benefits: dental.")
    p = jd.parse(flat)
    assert "Tableau" in p.text(jd.REQUIRED)
    assert "Python" in p.text(jd.PREFERRED)
    assert "dental" not in p.relevant_text


def test_salary_range_variants():
    assert jd.extract_salary("Pay: $75,000 - $95,000 per year") == (75000, 95000)
    assert jd.extract_salary("Base $80k–$100k") == (80000, 100000)
    assert jd.extract_salary("$25 - $30 per hour") == (52000, 62400)
    assert jd.extract_salary("No pay info here") is None


def test_years_required_takes_minimum(jd_text):
    assert jd.years_required(jd.parse(jd_text)) == 2
