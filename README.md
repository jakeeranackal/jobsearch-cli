# jobsearch-cli

A command-line tool for running a focused, defensible job search. It pulls openings from public job board APIs, scores them against your resume, reads each posting's requirements to show exactly what your resume is missing, rewrites your resume and cover letter per job, tracks every application, reads recruiter replies from Gmail, and tells you what's actually getting callbacks.

**Design principle:** the tool drafts and queues, *you* hit send. Automated submission to job boards violates the terms of service of LinkedIn, Indeed, Workday, Greenhouse, and most major ATSs, and recruiters can tell when an application was bot-submitted. This tool makes a real human search faster and sharper; it doesn't spray applications. It also never invents experience: `jobsearch check` flags any skill or number in an edited resume that isn't in your original.

**No API keys.** The tool does the mechanical half: finding, scoring, analyzing, tracking, drafting with [ADD] markers. The writing is yours, or Claude Code's if you use it (see [Using it with Claude Code](#using-it-with-claude-code)).

## Features

**Find**
- **Discover**: Greenhouse, Lever, Ashby, Workday, Workable, SmartRecruiters, and RSS. Add a company by pasting its careers URL.
- **Add anything**: paste a LinkedIn/Indeed listing (`add --paste`), a file, or a URL.
- **Match**: TF-IDF + keyword score against one or more resume tracks.
- **Quality filters**: duplicates merged, staffing agencies and stale (45d+) postings flagged, salary pulled from text, "no salary" flagged in pay-transparency states, sort by freshness.
- **Keyword cloud** across many listings: which skills show up most, which are required, which your resume lacks (`keywords --cloud`).

**Apply**
- **Analyze one job**: splits the posting into Requirements / Preferred / Responsibilities, weighs each skill by where and how often it appears, and compares to your resume. For example: "Tableau: 4x, required. Only in your skills list, so prove it in 1-2 bullets." It also flags wording gaps ("they say dashboards, you say reports").
- **Tailor**: reorders your bullets and skills by what the job weighs most and lists the exact edits to make. After you (or Claude Code) edit the wording, `check` re-scores it and flags anything not in your original resume, and `export` writes an ATS-safe .docx.
- **Apply kit** in one command: draft resume, cover letter, answers to standard form questions, company brief, and a `CLAUDE_BRIEF.md` with the edits and rules. It opens the posting and logs the application once you've sent it.
- **Outreach**: referral matches from your LinkedIn connections, people-search links, LinkedIn note + cold email drafts.
- **ATS check**: finds tables, text boxes, columns, header-only contact info, and scanned PDFs that applicant tracking systems can't read.

**After applying**
- **Track** status, contacts, and follow-up dates in a local SQLite database.
- **Gmail sync**: rejections, interview requests, and offers update statuses automatically.
- **Follow-ups and thank-yous** drafted as Gmail drafts (you send, or opt in to auto-send plain follow-ups).
- **Interviews**: logged to Google Calendar with the prep sheet attached; thank-you drafted after it ends.
- **Prep sheet**: what they'll probe, your proof for each, matching STAR stories from your story bank, likely questions.
- **Salary**: the posted range, what to anchor on, and negotiation scripts.

**Run it hands-off**
- `daily` discovers, scores, syncs email, drafts follow-ups/thank-yous, and sends you a digest (Telegram, Gmail, or SMTP).
- `schedule install` sets that up with Windows Task Scheduler or cron, with optional hourly alerts for strong new matches.
- `dashboard`: local drag-and-drop pipeline board.
- `bot`: Telegram bot for `/today`, `/apply <id>`, `/status`, `/stats` from your phone.
- `stats` / `report`: callback rate by resume version, tailored vs not, source, and how fast you applied.

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
jobsearch setup        # guided: you, your resume(s), target roles, companies, notifications
jobsearch list         # top matches
jobsearch analyze <job_id>
jobsearch apply <job_id>
```

That's it. `setup` asks everything in plain questions, writes `config.yaml`, and pulls your first jobs.

### Optional upgrades

| Want | Do |
|---|---|
| Gmail status sync, follow-up drafts, calendar | `jobsearch email connect --help` (one-time Google setup, about 5 min) |
| Phone digest + bot | `jobsearch bot --help` (Telegram, about 2 min) |
| Referral matches | `jobsearch network import Connections.csv` (LinkedIn data export) |
| Runs every morning by itself | `jobsearch schedule install --at 07:30 --hourly-alerts` |

Everything works without these.

## Using it with Claude Code

Open Claude Code in the `jobsearch-cli` folder; it reads `CLAUDE.md` and knows the commands. Then just talk:

- "Find me new data analyst jobs" runs discover, match and list, and walks you through the top ones.
- "What does the Ramp job want that my resume doesn't show?" runs `analyze` and explains the gaps.
- "Tailor my resume for it" builds the kit, rewrites the resume and letter from your real experience, runs `check` to prove nothing was invented, then `export`.
- "Run a mock interview for it" builds the prep sheet and quizzes you in chat.

Claude does the writing inside your normal Claude Code conversation. The tool never needs an API key, and nobody submits anything but you.

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
jobsearch tailor <id>                   # draft resume (.docx + .md) + edits to make
jobsearch check <id>                    # after editing: coverage + anything invented
jobsearch export <id>                   # edited .md to .docx
jobsearch letter <id>
jobsearch answers <id> -q "Why are you leaving your current role?"
jobsearch apply <id>                    # the whole kit + open posting + log it
jobsearch outreach <id>
jobsearch ats resumes/my_resume.docx

# after applying
jobsearch track <id> --status applied --contact-email recruiter@co.com
jobsearch applications                  # everything you're tracking
jobsearch followup --draft              # Gmail drafts for everything due
jobsearch email sync                    # statuses from recruiter replies
jobsearch interview add <id> --when "2026-10-14 14:00" --with "Sam Park"
jobsearch prep <id>
jobsearch thanks <id> --to sam@co.com --notes "the Snowflake migration"
jobsearch salary <id>

# insight + automation
jobsearch stats
jobsearch report --send
jobsearch digest --send
jobsearch daily
jobsearch dashboard
jobsearch bot
```

Every per-job output lands in `applications/<job_id>/` (gitignored).

## Your files

| File | What it is |
|---|---|
| `config.yaml` | Everything, written by `setup`. See `config.example.yaml` for all options. |
| `resumes/` | Your resumes (.docx, .pdf, or .txt). Optional `master` resume per track with every bullet you've written; tailoring picks from it. |
| `answers.yaml` | Your standard form answers (work auth, salary, start date...). `auto` fields get a per-job starting point. |
| `stories.yaml` | Your STAR stories, tagged by skill, matched to each job's prep sheet. |
| `jobsearch.db` | The database. |

All of these are gitignored. Nothing personal goes in the repo, so the project can be shared as-is.

## Project layout

```
src/jobsearch/
├── cli.py            # core commands; registers commands/*
├── commands/         # setup, find, apply, email, interviews, insights, automation, network
├── pipeline.py       # discover/match/apply-kit/digest shared by CLI, daily run, bot
├── jd.py             # job description sections, salary, years
├── keywords.py       # per-job gap analysis + cross-listing keyword cloud
├── data/skills.txt   # skill lexicon with aliases (edit freely)
├── tailor.py         # reorder for a job, check edits, fabrication check
├── resume_io.py      # read/write txt/docx/pdf, ATS check
├── letters.py        # cover letter, outreach, follow-up, thank-you drafts
├── answers.py        # application-form answer bank
├── interview.py      # prep sheets, story matching, salary
├── company.py        # company brief, board slug probe
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
