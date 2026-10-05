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
                          jobsearch list
```

### v0.2: from a matched job to an application

```
jobs row ──► jd.parse()            sections: required / preferred / responsibilities / ignored
               │
               ▼
         keywords.analyze_job()    lexicon terms weighted by section + title,
               │                   compared to resume bullets vs skills list
               ▼                   ──► GOOD / BURIED / STRENGTHEN / WORDING / MISSING
         tailor.tailor()           reorder bullets/skills by job weight, list edits
               │
               ▼
         pipeline.prepare()        posting.md, analysis.md, reordered resume .md
               │                   in applications/<company>-<role>/
               ▼
         you / Claude Code edit    the wording, cover letter, emails: in conversation, real facts only
               │
               ▼
         tailor.check()            re-score + flag skills/numbers not in the original
         export                    rebuild the .docx from the edited .md
               │
               ▼
         applications/<job>/  +  applications row (status, resume_path, bundle_dir)
```

### After applying

```
Gmail ──► inbox.classify() ──► inbox.match_job() ──► db.update_application()  (forward only)
interviews table + applications.next_followup_at ──► digest ("send a thank-you", "follow up")
email draft <file> ──► Gmail Drafts (a file you or Claude wrote; never sent)
status_history ──► stats.funnel() / stats.weekly()
automation.run_daily() runs all of the above, then notify.send(digest)
```

## Why these choices

- **SQLite, not Postgres**: this is a single-user CLI. The DB file lives next to the project. No server, no docker, no migrations to manage. If a multi-user version ships, swap with SQLAlchemy.
- **TF-IDF + keyword density, not embeddings**: explainable, fast, no API key needed, no cost. For the volume of jobs a single person looks at (low hundreds), this is plenty. Embeddings can replace `matcher.py` in v0.3 without changing the rest.
- **httpx, not requests**: same ergonomics, async-ready if v0.2 needs concurrent fetches.
- **Lexicon, not free-text NLP, for keywords**: `data/skills.txt` maps aliases ("PowerBI", "power bi desktop") to one skill so counts are honest and the output is explainable. Repeated phrases outside the lexicon are still surfaced. Users extend it via `keywords.extra` in config.
- **Section-aware weighting**: a skill in Requirements or the title outweighs one in Nice-to-have, and benefits/EEO text is ignored. Headings are recognized by phrase; checked against live Greenhouse, Lever and Ashby postings (~95% get a Requirements section).
- **No AI service, no API key**: the tool does what code is good at (pulling hundreds of postings, counting, remembering, checking). The writing is done by the person, usually with Claude Code in conversation (`CLAUDE.md` tells it how). `check` then verifies nothing was invented.
- **Email only moves status forward**: an "application received" after an interview invite never downgrades the row.
- **Drafts go to disk as Markdown**: the user *will* edit them. Markdown is the path of least resistance and pastes cleanly into email, Google Docs, or an ATS textarea.

## Adding a new source

1. Create `src/jobsearch/sources/yoursource.py` exposing `fetch(slug, ...) -> list[dict]`.
2. Make sure each returned dict has at least: `id`, `source`, `source_company`, `title`, `description`, `url`. Other fields are optional.
3. Use a stable `id` format like `yoursource:slug:remote_id` so re-runs don't create duplicates.
4. Register the source in `cli.discover()` alongside greenhouse/lever/ashby.

## What's deliberately *not* here

- **Auto-submitting applications.** This violates the ToS of every major job board and ATS, and recruiters can spot bot-submitted applications. The tool drafts; the human sends.
- **Sending applications or messages on its own.** `email draft` saves to Gmail Drafts; only the digest to yourself is ever sent.
- **Scraping LinkedIn/Indeed.** Paste listings with `add --paste`; import your own connections from LinkedIn's data export.
- **A hosted web app.** The dashboard is a local, stdlib-only page on 127.0.0.1 over the same DB.
