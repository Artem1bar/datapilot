"""AI-powered data analysis service using Claude."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "analysis_system.txt"
_SYSTEM_PROMPT: str | None = None


def _get_client() -> Anthropic:
    """Create a fresh client each call to pick up the latest API key."""
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


def _build_dataset_context(profile_json: dict, sample_rows: list[dict]) -> str:
    """Format the dataset profile and sample rows for inclusion in the system message."""
    parts = [
        "=== Dataset Profile ===",
        json.dumps(profile_json, indent=2, default=str),
        "",
        "=== Sample Rows (first 20) ===",
        json.dumps(sample_rows, indent=2, default=str),
    ]
    return "\n".join(parts)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from text, handling optional markdown code fences."""
    # Try to find JSON inside code fences first
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Try parsing the entire text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find a top-level JSON object in the text
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def analyze_data(
    question: str,
    profile_json: dict,
    sample_rows: list[dict],
    history: list[dict],
) -> dict[str, Any]:
    """Send a user question to Claude for data analysis.

    This is a sync function — call via asyncio.to_thread() from async code.
    """
    system_prompt = _load_system_prompt()
    dataset_context = _build_dataset_context(profile_json, sample_rows)
    full_system = f"{system_prompt}\n\n{dataset_context}"

    # Build messages from history
    messages: list[dict[str, str]] = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Append the new user question
    messages.append({"role": "user", "content": question})

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4096,
            system=full_system,
            messages=messages,
        )
        raw_text = response.content[0].text
    except Exception:
        logger.exception("Claude API call failed")
        return {"answer": "Sorry, the analysis service is temporarily unavailable.", "charts": [], "tables": []}

    # Parse structured response
    parsed = _extract_json(raw_text)
    if parsed is not None:
        return {
            "answer": parsed.get("answer", raw_text),
            "charts": parsed.get("charts", []),
            "tables": parsed.get("tables", []),
        }

    # Fallback: return raw text as the answer
    logger.warning("Failed to parse JSON from Claude response; returning raw text.")
    return {"answer": raw_text, "charts": [], "tables": []}
