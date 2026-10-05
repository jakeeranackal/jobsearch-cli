# jobsearch-cli: notes for Claude Code

This tool does the mechanical half of a job search (find, score, analyze, track).
You, Claude Code, do the writing half in conversation. There is no API key and
the tool never calls an AI service.

## Before running anything
Activate the virtual environment in this folder:
- Mac/Linux: `source .venv/bin/activate`
- Windows: `.venv\Scripts\activate`

## Common requests and what to run
| The person says | Run |
|---|---|
| "find me jobs" / "what's new" | `jobsearch discover`, `jobsearch match`, `jobsearch list --fresh 7` |
| "add this job" (pasted text) | save it to a .txt file, then `jobsearch add --file job.txt --title "..." --company "..."` |
| "what does this job want" | `jobsearch analyze <id>` and explain the table in plain words |
| "tailor my resume for X" | see the workflow below |
| "I applied" | `jobsearch track <id> --status applied` |
| "what do I follow up on" | `jobsearch followup` |
| "prep me for the interview" | `jobsearch prep <id>`, then run a mock interview in chat from that sheet |
| "how am I doing" | `jobsearch stats` and `jobsearch report` |
| "what skills do jobs want" | `jobsearch keywords --cloud cloud.html` |

## Tailoring workflow
1. `jobsearch apply <id> --no-open` builds `applications/<id>/` and asks if it was submitted. Answer no until the person says they sent it.
2. Read `applications/<id>/CLAUDE_BRIEF.md` and `analysis.md`.
3. Edit the resume `.md` in that folder and `cover_letter.md`, following the brief's rules.
4. `jobsearch check <id>`. Fix every red warning (remove it, or ask the person whether it's true).
5. `jobsearch export <id>` rebuilds the .docx from the .md.
6. Hand the files back. The person reviews them and submits on the company's site.

## Rules
- Never invent experience, tools, employers, dates, degrees, or numbers. Ask instead.
- Never submit an application or send an email on the person's behalf.
- Mirror the posting's words only where they're accurate.
