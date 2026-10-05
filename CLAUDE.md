# jobsearch-cli: notes for Claude Code

This tool does the mechanical half of a job search: find, score, analyze, track, check.
You do the writing half in conversation. There is no API key and the tool never
calls an AI service.

## Running it
Run commands from this folder with its virtual environment:
- Mac/Linux: `.venv/bin/jobsearch <command>`
- Windows: `.venv\Scripts\jobsearch.exe <command>`

## Common requests
| The person says | Do |
|---|---|
| "find me jobs" / "what's new" | `discover`, `match`, `list --fresh 7`; explain the top 5 in plain words |
| "add this job" (pasted text) | save it to a .txt file, `add --file job.txt --title "..." --company "..."` |
| "what does this job want" | `analyze <id>`, then explain the table: what's covered, buried, missing |
| "tailor my resume for X" | the workflow below |
| "write the cover letter" | read the job folder's posting.md and the edited resume, write cover-letter.md there |
| "I applied" / "I heard back" | `track <id> --status applied` (or interviewing, rejected, offer) |
| "who do I follow up with" | `followup`; offer to write each email (they send it) |
| "prep me for the interview" | read posting.md and the resume, research the company, likely questions, mock interview in chat |
| "what skills keep coming up" | `keywords --cloud cloud.html` |

## Tailoring workflow
1. `prepare <id>` writes posting.md, analysis.md and a reordered resume .md into the job's folder.
2. Read analysis.md and posting.md. Rewrite the resume .md: mirror their wording where it's true, lead with what they weigh most, prove buried skills in bullets.
3. `check <id>`. Fix every red warning: remove it, or ask the person whether it's true.
4. `export <id>` writes the .docx.
5. Hand it back. The person reviews and submits on the company's site.

## Rules
- Never invent experience, tools, employers, dates, degrees, or numbers. Ask instead.
- Never submit an application or send an email. `email draft` only saves to Gmail Drafts.
- Mirror the posting's words only where they're accurate.
