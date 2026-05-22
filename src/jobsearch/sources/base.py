"""Shared utilities for source adapters."""
from __future__ import annotations

import re
from html import unescape


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(s: str | None) -> str:
    """Cheap HTML->text. Sufficient for matcher input."""
    if not s:
        return ""
    text = _TAG_RE.sub(" ", s)
    text = unescape(text)
    return _WS_RE.sub(" ", text).strip()
