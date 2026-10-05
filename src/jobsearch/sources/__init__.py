"""Job source adapters.

Each module here exposes a fetch() function returning a list of normalized
job dicts with the shape expected by db.upsert_job.
"""
from . import ashby, greenhouse, lever, manual, rss, smartrecruiters, workable, workday

__all__ = ["greenhouse", "lever", "ashby", "rss", "workday", "smartrecruiters",
           "workable", "manual"]
