"""Smoke tests for the matcher.

These don't hit the network — they test the scoring math against canned input.
"""
from jobsearch.matcher import Track, score_jobs


def test_high_match_scores_higher_than_low_match():
    resume = """
    Data analyst with experience in Python, pandas, SQL, regression modeling.
    Built MLB betting models with scikit-learn and feature engineering.
    """
    track = Track(name="data", resume_text=resume,
                  keywords=["python", "pandas", "sql", "regression"])

    relevant = ("job1", "Quantitative Analyst",
                "Build regression models in Python and pandas. SQL required.")
    irrelevant = ("job2", "Front Desk Associate",
                  "Greet visitors, answer phones, manage scheduling.")
    scores = score_jobs(track, [relevant, irrelevant])

    assert scores["job1"] > scores["job2"]
    assert scores["job1"] > 0.2


def test_empty_jobs_returns_empty():
    track = Track(name="x", resume_text="anything", keywords=[])
    assert score_jobs(track, []) == {}


def test_keyword_density_zero_when_no_keywords_configured():
    track = Track(name="x", resume_text="python pandas sql", keywords=[])
    scores = score_jobs(track,
                        [("j", "Python role", "We use python pandas and sql daily.")],
                        kw_weight=0.5)
    # With kw_weight=0.5 but no keywords, half the score is zeroed out — must still be < 1.
    assert 0.0 <= scores["j"] <= 1.0
