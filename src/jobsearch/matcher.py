"""Resume <-> job matching.

Scoring formula:
    score = (1 - kw_weight) * tfidf_cosine + kw_weight * keyword_density
Where keyword_density is the fraction of the configured keywords for the
track that appear in the job description (case-insensitive substring).

This is intentionally simple and explainable. The whole point is to surface
the right 20 jobs from a list of 400 — not to be a recommender system.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Track:
    name: str
    resume_text: str
    keywords: list[str]


def load_track(name: str, path: str | Path, keywords: list[str]) -> Track:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Resume for track '{name}' not found at {p}. "
            f"Drop a plain-text resume there or update config.yaml."
        )
    return Track(name=name, resume_text=p.read_text(encoding="utf-8"),
                 keywords=[k.lower() for k in keywords])


def score_jobs(track: Track, jobs: list[tuple[str, str, str]],
               kw_weight: float = 0.35) -> dict[str, float]:
    """Score every job against the track. Returns {job_id: score}.

    jobs is a list of (job_id, title, description) tuples.
    """
    if not jobs:
        return {}

    corpus = [track.resume_text] + [f"{t}\n{d}" for _, t, d in jobs]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1, max_df=0.95)
    matrix = vec.fit_transform(corpus)
    sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()

    out: dict[str, float] = {}
    for (job_id, title, desc), tfidf in zip(jobs, sims):
        kw_density = _keyword_density(f"{title}\n{desc}", track.keywords)
        score = (1.0 - kw_weight) * float(tfidf) + kw_weight * kw_density
        out[job_id] = round(score, 4)
    return out


def _keyword_density(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw in text_lower)
    return hits / len(keywords)
