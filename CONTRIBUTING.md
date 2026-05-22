# Contributing

Thanks for considering a contribution. A few guidelines.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Scope

This tool is intentionally narrow. PRs are most welcome for:

- New source adapters (additional ATSs, industry-specific boards with public APIs or RSS)
- Matcher improvements that stay explainable
- Better follow-up reminders or status workflows
- Docs and examples

PRs that will likely be declined:

- Anything that automates submission to a job board or ATS (against the ToS of every major platform, and bad for users)
- Anything that scrapes a site whose ToS forbids it
- Wholesale rewrites without a discussion issue first

## Style

- Format with `ruff format` (or black) before submitting
- Type hints where they help
- Keep functions small and dependencies few

## PR checklist

- [ ] Tests pass: `pytest`
- [ ] New behavior has a test
- [ ] README updated if behavior or commands changed
- [ ] No personal data committed (resumes, config.yaml, jobsearch.db)
