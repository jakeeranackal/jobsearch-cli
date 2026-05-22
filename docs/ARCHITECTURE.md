# Architecture

## Data flow

```
                  ┌────────────────────┐
                  │   config.yaml      │
                  │ (sources, tracks,  │
                  │  filters)          │
                  └─────────┬──────────┘
                            │
       ┌────────────────────┼────────────────────┐
       ▼                    ▼                    ▼
  greenhouse.fetch     lever.fetch           ashby.fetch     rss.fetch
       │                    │                    │              │
       └────────────────────┴───────┬────────────┴──────────────┘
                                    ▼
                       passes_filters() — drop
                       jobs we don't want to see
                                    ▼
                            db.upsert_job()
                                    ▼
                          ┌───────────────────┐
                          │   jobs table      │
                          └───────────────────┘
                                    ▼
                          matcher.score_jobs()
                          per resume track
                                    ▼
                          ┌───────────────────┐
                          │   scores table    │
                          └───────────────────┘
                                    ▼
                          jobsearch list / draft
                                    ▼
                          drafter.render()
                                    ▼
                       drafts/{job_id}.md  +  applications row
```

## Why these choices

- **SQLite, not Postgres**: this is a single-user CLI. The DB file lives next to the project. No server, no docker, no migrations to manage. If a multi-user version ships, swap with SQLAlchemy.
- **TF-IDF + keyword density, not embeddings**: explainable, fast, no API key needed, no cost. For the volume of jobs a single person looks at (low hundreds), this is plenty. Embeddings can replace `matcher.py` in v0.3 without changing the rest.
- **httpx, not requests**: same ergonomics, async-ready if v0.2 needs concurrent fetches.
- **Drafts go to disk as Markdown**: the user *will* edit them. Markdown is the path of least resistance and pastes cleanly into email, Google Docs, or an ATS textarea.

## Adding a new source

1. Create `src/jobsearch/sources/yoursource.py` exposing `fetch(slug, ...) -> list[dict]`.
2. Make sure each returned dict has at least: `id`, `source`, `source_company`, `title`, `description`, `url`. Other fields are optional.
3. Use a stable `id` format like `yoursource:slug:remote_id` so re-runs don't create duplicates.
4. Register the source in `cli.discover()` alongside greenhouse/lever/ashby.

## What's deliberately *not* here

- **Auto-submitting applications.** This violates the ToS of every major job board and ATS, and recruiters can spot bot-submitted applications. The tool drafts; the human sends.
- **Resume parsing from PDF/DOCX.** Plain text only. Users keep their own resume source files; the tool stays a tool.
- **A web UI.** v1 is a CLI. A Streamlit or FastAPI layer can sit on top of the same DB later.
