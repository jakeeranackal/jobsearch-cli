"""Shared utilities for source adapters."""
from __future__ import annotations

import re
from html import unescape


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_BLOCK_RE = re.compile(r"<\s*(br|/p|/div|/h[1-6]|/ul|/ol|/tr)\b[^>]*>", re.I)
_LI_RE = re.compile(r"<\s*li\b[^>]*>", re.I)
_HEADING_RE = re.compile(r"<\s*h[1-6]\b[^>]*>", re.I)
_SPACES_RE = re.compile(r"[ \t ]+")


def strip_html(s: str | None) -> str:
    """Cheap HTML->text on one line. Kept for callers that want flat text."""
    if not s:
        return ""
    text = _TAG_RE.sub(" ", s)
    text = unescape(text)
    return _WS_RE.sub(" ", text).strip()


def html_to_text(s: str | None) -> str:
    """HTML->text that keeps line breaks and list bullets.

    Section parsing (Requirements vs Benefits) needs the structure, so sources
    store descriptions in this form. Greenhouse double-escapes its HTML, hence
    the unescape before stripping tags.
    """
    if not s:
        return ""
    s = unescape(s) if "&lt;" in s else s
    s = _HEADING_RE.sub("\n", s)
    s = _LI_RE.sub("\n- ", s)
    s = _BLOCK_RE.sub("\n", s)
    s = _TAG_RE.sub(" ", s)
    s = unescape(s)
    lines = [_SPACES_RE.sub(" ", ln).strip() for ln in s.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln in ("", "-"):
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(ln)
    return "\n".join(out).strip()
