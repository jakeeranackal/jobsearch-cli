# jobsearch-cli

A command-line tool for running a focused, defensible job search. It pulls openings from public job board APIs, scores them against your resume, tracks applications and follow-ups in a local SQLite database, and drafts tailored cover letters you review before sending.

**Design principle:** the tool drafts and queues, *you* hit send. Automated submission to job boards violates the terms of service of LinkedIn, Indeed, Workday, Greenhouse, and most major ATSs, and recruiters can tell when an application was bot-submitted. This tool is built to make a real human search faster and more organized, not to spray applications.

## Features

- **Discover** — fetches active postings from Greenhouse, Lever, and Ashby public job board APIs, plus any RSS feed you configure
- **Match** — scores each job against your resume(s) using TF-IDF similarity plus configurable keyword boosts; supports multiple resume tracks (e.g. operations vs. data)
- **Track** — SQLite database of every application with status, dates, contacts, and notes
- **Draft** — generates a tailored cover letter draft per job into a `drafts/` folder for review and editing
- **Follow up** — surfaces applications due for a check-in based on time since last contact

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/jobsearch-cli.git
cd jobsearch-cli
python -m venv .venv
source .venv/bin/activate    # on Windows: .venv\Scripts\activate
pip install -e .
```

## Quick start

```bash
# One-time setup: creates ./jobsearch.db and ./config.yaml from the example
jobsearch init

# Edit config.yaml — add your user info, resume paths, and source companies
# Drop plain-text resumes into ./resumes/

# Pull jobs from every configured source
jobsearch discover

# Score every job against your resume tracks
jobsearch match

# See top matches
jobsearch list --min-score 0.25

# Draft a cover letter for a specific job (writes to ./drafts/)
jobsearch draft <job_id>

# Log that you applied
jobsearch track <job_id> --status applied --notes "Submitted via company site"

# See what needs a follow-up
jobsearch followup
```

## Configuration

`config.yaml` controls everything. The relevant sections:

```yaml
user:
  name: Your Name
  email: you@example.com
  phone: "555-555-5555"
  location: City, ST

resume_tracks:
  primary:
    path: resumes/resume.txt
    keywords: [python, sql, analytics]

sources:
  greenhouse: [company-slug-1, company-slug-2]
  lever: [company-slug-1]
  ashby: [company-slug-1]
  rss:
    - name: Example Careers Feed
      url: https://example.com/careers/feed.xml
```

To find a company's Greenhouse / Lever / Ashby slug, look at their careers page URL — it's the subdomain or path segment (e.g. `boards.greenhouse.io/notion` → slug is `notion`).

## Project layout

```
jobsearch-cli/
├── src/jobsearch/
│   ├── cli.py           # click-based CLI entrypoints
│   ├── db.py            # SQLite schema + helpers
│   ├── matcher.py       # TF-IDF + keyword scoring
│   ├── drafter.py       # Jinja2 cover letter rendering
│   ├── sources/         # one adapter per job source
│   └── templates/       # cover letter templates
├── resumes/             # your plain-text resumes (gitignored)
├── drafts/              # generated cover letter drafts (gitignored)
├── config.example.yaml
└── jobsearch.db         # local database (gitignored)
```

## Roadmap

- v0.1 (current): discover, match, track, draft for Greenhouse/Lever/Ashby/RSS
- v0.2: sport- and industry-specific source adapters (Teamwork Online, music label career RSS bundles)
- v0.3: optional Slack/Discord webhook for daily top-match digest
- v0.4: resume keyword gap analysis ("you're missing X for this role")

## License

MIT — see [LICENSE](LICENSE).

## Contributing

PRs welcome. Run `pytest` before submitting. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data flow.
