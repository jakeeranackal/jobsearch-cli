# jobsearch-cli

A command-line tool for the mechanical half of a job search. It pulls openings from public job board APIs, scores them against your resume, reads each posting's requirements to show exactly what your resume is missing, tracks every application and follow-up, reads recruiter replies from Gmail, and tells you what's actually getting callbacks.

The writing half (rewording your resume, cover letters, emails, interview prep) is done by you, or by Claude Code in conversation. The tool hands it the facts and then checks the result. **No API keys, no AI service calls.**

**Design principle:** the tool prepares, *you* hit send. Automated submission to job boards violates the terms of service of LinkedIn, Indeed, Workday, Greenhouse, and most major ATSs, and recruiters can tell when an application was bot-submitted. And it never lets invented experience through: `jobsearch check` flags any skill or number in an edited resume that isn't in your original.

## What the tool does vs. what Claude Code does

| Tool (code: fast, free, consistent, remembers) | Claude Code (judgment and writing) |
|---|---|
| Pull jobs from 6 job boards every day | Walk you through the best matches |
| Merge duplicates, flag stale/agency/no-salary posts | Judge real fit for the one job you care about |
| Score every job against your resume | Rewrite your resume in the job's wording, truthfully |
| `analyze`: weigh each skill by section, compare to your resume | Cover letters, form answers, outreach, thank-yous |
| `keywords`: most-wanted skills across all postings | Company research (web search) |
| `check`: catch invented skills or numbers | Interview prep and mock interviews |
| Track statuses, follow-up dates, stats; read Gmail replies | Draft the follow-up email when one is due |

## Features

**Find**
- **Discover**: Greenhouse, Lever, Ashby, Workday, Workable, SmartRecruiters, and RSS. Add a company by pasting its careers URL.
- **Add anything**: paste a LinkedIn/Indeed listing (`add --paste`), a file, or a URL.
- **Match**: TF-IDF + keyword score against one or more resume tracks.
- **Quality filters**: duplicates merged, staffing agencies and stale (45d+) postings flagged, salary from structured fields or text, "no salary" flagged in pay-transparency states, sort by freshness.
- **Keyword cloud** across many listings: which skills show up most, which are required, which your resume lacks.

**One job**
- **Analyze**: splits the posting into Requirements / Preferred / Responsibilities, weighs each skill by where and how often it appears, and compares to your resume. For example: "Tableau: 4x, required. Only in your skills list, so prove it in 1-2 bullets"; "they say dashboards, you say reports".
- **Prepare**: one folder per application with the full posting, the analysis, and your resume reordered for the job, ready to edit.
- **Check / export**: after editing, re-score coverage and flag anything not in your original resume; then write an ATS-safe .docx.
- **Contacts**: people you know there (from your LinkedIn export) and search links for the recruiter and hiring manager.
- **ATS check**: finds tables, text boxes, columns, and scanned PDFs that applicant tracking systems can't read.

**After applying**
- **Track** statuses, notes, contacts and follow-up dates; `applications` and `followup` show what's where and what's due.
- **Gmail sync** (optional): rejections, interview requests and offers update statuses automatically. `email draft` puts an email you wrote into Gmail Drafts; nothing is ever sent.
- **Interviews**: logged (and added to Google Calendar if connected).

**Hands-off**
- `daily`: discover, score, sync Gmail statuses, and send you a digest (new matches, follow-ups due, thank-yous to send) via Telegram, Gmail or SMTP.
- `schedule install`: runs `daily` every morning (Windows Task Scheduler or cron), optional hourly alerts.
- `dashboard`: local drag-and-drop pipeline board. `bot`: Telegram commands from your phone.
- `stats` / `report`: callback rate by resume version, source, and how fast you applied.

## Install

```bash
git clone https://github.com/jakeeranackal/jobsearch-cli.git
cd jobsearch-cli
python -m venv .venv
source .venv/bin/activate    # on Windows: .venv\Scripts\activate
pip install -e .             # add ".[google]" for Gmail/Calendar
```

## Quick start

```bash
jobsearch setup        # guided: you, your resume, target roles, companies
jobsearch list         # top matches
jobsearch analyze <job_id>
jobsearch prepare <job_id>
```

## Using it with Claude Code

Open Claude Code in this folder; it reads `CLAUDE.md` and knows the commands and rules. Then just talk:

- "Find me new data analyst jobs" runs discover, match and list, and walks you through the top ones.
- "What does the Ramp job want that my resume doesn't show?" runs `analyze` and explains it.
- "Tailor my resume for it" runs `prepare`, rewrites the resume from your real experience, runs `check` until nothing is flagged, then `export`.
- "Write the cover letter", "prep me for the interview", "who should I follow up with": Claude writes these in chat using the files in the job's folder.

## Commands

```bash
# find
jobsearch discover                      # pull every configured board
jobsearch match                         # score against your resume tracks
jobsearch list --fresh 7 --hide-flagged --sort fresh
jobsearch add --paste                   # paste a LinkedIn/Indeed listing
jobsearch add --url <posting url>
jobsearch keywords --title analyst --cloud cloud.html
jobsearch companies add https://boards.greenhouse.io/notion

# one job
jobsearch analyze <id>                  # requirements vs your resume, with actions
jobsearch prepare <id>                  # posting.md, analysis.md, resume reordered for the job
jobsearch check <id>                    # after editing: coverage + anything invented
jobsearch export <id>                   # edited .md to .docx
jobsearch contacts <id>
jobsearch ats resumes/my_resume.docx

# after applying
jobsearch track <id> --status applied --contact-email recruiter@co.com
jobsearch applications                  # everything you're tracking
jobsearch followup                      # what's due
jobsearch email sync                    # statuses from recruiter replies (Gmail)
jobsearch email draft note.txt --to sam@co.com --subject "Thank you"
jobsearch interview add <id> --when "2026-10-14 14:00" --with "Sam Park"

# insight + automation
jobsearch stats
jobsearch report
jobsearch digest --send
jobsearch daily
jobsearch schedule install --at 07:30 --hourly-alerts
jobsearch dashboard
jobsearch bot
```

Application folders go to `applications/<company>-<role>/` (set `applications_dir` in config to put them elsewhere).

## Your files

| File | What it is |
|---|---|
| `config.yaml` | Everything, written by `setup`. See `config.example.yaml` for all options. |
| `resumes/` or any path | Your resume: .md, .docx, .pdf, or .txt. Optional `master` resume per track with every bullet you've written. |
| `jobsearch.db` | The database. |
| `applications/` | One folder per job you prepare. |

All of these are gitignored. Nothing personal goes in the repo.

## Project layout

```
src/jobsearch/
├── cli.py            # core commands; registers commands/*
├── commands/         # setup, find, apply, email, interviews, insights, automation, network
├── pipeline.py       # discover/match/prepare/digest shared by CLI, daily run, bot
├── jd.py             # job description sections, salary, years
├── keywords.py       # per-job gap analysis + cross-listing keyword cloud
├── data/skills.txt   # skill lexicon with aliases (edit freely)
├── tailor.py         # reorder for a job, check edits, fabrication check
├── resume_io.py      # read/write md/txt/docx/pdf, ATS check
├── company.py        # job board slug probe
├── network.py        # LinkedIn connections, referrals
├── quality.py        # dedupe, flags, freshness
├── inbox.py          # email classification + status updates
├── google_api.py     # Gmail + Calendar
├── notify.py         # Telegram / Gmail / SMTP delivery
├── stats.py          # funnel stats + weekly report
├── automation.py     # daily run + scheduler install
├── dashboard.py      # local web board
├── bot.py            # Telegram bot
└── sources/          # one adapter per job board
```

## License

MIT, see [LICENSE](LICENSE).

## Contributing

PRs welcome. Run `pytest` before submitting. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data flow.
