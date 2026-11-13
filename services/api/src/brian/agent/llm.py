"""Shared Claude client configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import anthropic

from brian.config import Settings, get_settings

# Server-side refusal fallback: if a safety classifier declines a request, the API re-runs it on
# the model Anthropic recommends for that category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailableError(RuntimeError):
    """Raised when Claude is disabled by configuration."""


@lru_cache
def get_client() -> anthropic.AsyncAnthropic:
    # Credentials resolve from the environment (ANTHROPIC_API_KEY, ...). Retries on 429/5xx are
    # handled by the SDK.
    return anthropic.AsyncAnthropic(max_retries=3)


def require_client(settings: Settings | None = None) -> anthropic.AsyncAnthropic:
    settings = settings or get_settings()
    if not settings.llm_enabled:
        raise LLMUnavailableError("LLM features are disabled (LLM_ENABLED=false)")
    return get_client()


def request_extras(settings: Settings | None = None) -> dict[str, Any]:
    """Keyword arguments every `client.beta.messages.*` call shares."""
    settings = settings or get_settings()
    if not settings.llm_refusal_fallbacks:
        return {}
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}


def dump_content(blocks: list[Any]) -> list[dict[str, Any]]:
    """Serialize response content blocks exactly as the SDK sends them back in a request, so stored
    history can be replayed verbatim (thinking blocks included)."""
    out: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            out.append(block)
        else:
            out.append(
                block.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_unset=True,
                    exclude=getattr(block, "__api_exclude__", None),
                )
            )
    return out


def text_of(blocks: list[Any]) -> str:
    """Concatenate the visible text blocks of a response."""
    parts = []
    for block in blocks:
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "text":
            parts.append(block["text"] if isinstance(block, dict) else block.text)
    return "".join(parts).strip()
