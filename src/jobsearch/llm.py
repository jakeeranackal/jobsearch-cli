"""Thin wrapper over the Claude API for the rewrite/drafting features.

Optional: every caller has a non-AI fallback, so the tool works without a key.
Credentials resolve the SDK's normal way (ANTHROPIC_API_KEY, or an
`ant auth login` profile). Model and effort are configurable under `llm:`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
# Server-side fallback reroutes a safety-classifier decline to another model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


def _settings(cfg: dict | None) -> dict:
    return (cfg or {}).get("llm") or {}


def available(cfg: dict | None = None) -> bool:
    if _settings(cfg).get("enabled") is False:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def _client():
    import anthropic

    return anthropic.Anthropic()


def _create(cfg: dict | None, system: str, prompt: str, *, max_tokens: int,
            effort: str | None = None, output_format: dict | None = None):
    import anthropic

    s = _settings(cfg)
    output_config: dict = {"effort": effort or s.get("effort") or DEFAULT_EFFORT}
    if output_format:
        output_config["format"] = output_format
    try:
        response = _client().beta.messages.create(
            model=s.get("model") or DEFAULT_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LLMError("Claude API key missing or invalid. Set ANTHROPIC_API_KEY.") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Claude API rate limit hit. Try again in a minute.") from e
    except anthropic.BadRequestError as e:
        raise LLMError(f"Claude API rejected the request: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Couldn't reach the Claude API. Check your connection.") from e

    if response.stop_reason == "refusal":
        raise LLMError("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude's response was cut off (max_tokens).")
    return response


def ask_text(cfg: dict | None, system: str, prompt: str, *, max_tokens: int = 8000,
             effort: str | None = None) -> str:
    response = _create(cfg, system, prompt, max_tokens=max_tokens, effort=effort)
    return "".join(b.text for b in response.content if b.type == "text").strip()


def ask_json(cfg: dict | None, system: str, prompt: str, schema: dict, *,
             max_tokens: int = 16000, effort: str | None = None) -> dict:
    response = _create(cfg, system, prompt, max_tokens=max_tokens, effort=effort,
                       output_format={"type": "json_schema", "schema": schema})
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError("Claude returned malformed JSON.") from e
