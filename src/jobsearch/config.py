"""Shared paths, config loading, and the console every command prints to."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from rich.console import Console

CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG = Path("config.example.yaml")
DRAFTS_DIR = Path("drafts")
RESUMES_DIR = Path("resumes")
APPLICATIONS_DIR = Path("applications")
SECRETS_DIR = Path(".secrets")

console = Console()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(
            "[red]No config.yaml found.[/red] Run `jobsearch setup` (guided) or `jobsearch init`.",
        )
        sys.exit(1)
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def try_load_config() -> dict:
    """Like load_config but returns {} instead of exiting. For optional features."""
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def safe_name(job_id: str) -> str:
    """Filename-safe version of a job id."""
    return job_id.replace(":", "_").replace("/", "_").replace("\\", "_")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def application_dir(job: dict, cfg: dict | None = None) -> Path:
    """Folder for one application: <applications_dir>/<company>-<role>.

    applications_dir defaults to ./applications; the beginner guide sets it to
    ../applications so the tool and the Claude skills share one folder.
    """
    base = Path((cfg or {}).get("applications_dir") or APPLICATIONS_DIR)
    d = base / f"{slug(company_name(job))}-{slug(job.get('title') or 'role')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def company_name(job: dict) -> str:
    """Human company name. Slugs like 'acme-corp' become 'Acme Corp'."""
    raw = job.get("company_name") or job.get("source_company") or ""
    if raw and raw == raw.lower():
        return raw.replace("-", " ").replace("_", " ").title()
    return raw
