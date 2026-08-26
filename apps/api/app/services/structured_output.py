"""Structured output from Claude via forced tool use.

Both the cleaning-plan generator and the verification agent need Claude to
return a structured object. Scraping JSON out of free text is fragile — the
model wraps it in prose or code fences, or emits subtly malformed JSON that a
regex/brace-matcher mis-parses. Forcing a single tool call instead makes the
SDK hand back an already-parsed dict.

Why tool use and not ``messages.parse`` / ``output_config.format``:
    * ``output_config.format`` is unsupported on Claude Sonnet 4.6 (the
      verification agent's model) — it would 400.
    * The cleaning-step ``params`` object is freeform (its shape varies per
      operation), which a strict structured-output schema (``additionalProperties:
      false`` on every object) cannot express.
Forced tool use is the structured mechanism that works on every model and
accepts a freeform object, so both call sites share this one helper.

Backends:
    This module is also the dispatch point for ``settings.LLM_BACKEND``. Under
    ``"api"`` (the default, and the only backend production accepts) calls go
    through the Anthropic SDK as described above. Under ``"cli"`` they are
    routed to :mod:`app.services.llm_cli`, which shells out to the local
    ``claude`` binary so usage bills a Claude subscription instead of an API
    key — closed testing only, and structurally weaker (see that module).
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCallResult:
    """Parsed input from a forced tool call.

    ``raw_content`` is the full ``response.content`` (including the tool_use
    block), needed to continue a multi-turn conversation — e.g. appending the
    assistant turn plus a ``tool_result`` when regenerating after validation.
    """

    input: dict[str, Any]
    tool_use_id: str
    raw_content: list[Any]


def request_tool_call(
    client: Anthropic,
    *,
    model: str,
    system: Any,
    messages: list[dict[str, Any]],
    tool: dict[str, Any],
    max_tokens: int,
    rate_limit_retries: int = 2,
    rate_limit_wait: float = 15.0,
) -> ToolCallResult:
    """Call Claude, forcing it to invoke ``tool``, and return the parsed input.

    Retries on ``RateLimitError`` up to ``rate_limit_retries`` attempts, waiting
    ``rate_limit_wait`` seconds between them. Raises ``ValueError`` if the
    response contains no tool_use block for ``tool`` — which should not happen
    under forced ``tool_choice`` but guards against an unexpected response shape.

    Under ``LLM_BACKEND="cli"`` this delegates to the CLI backend, which has no
    forced tool use and parses JSON out of the reply instead; ``client`` is
    unused on that path.
    """
    tool_name = tool["name"]

    if settings.LLM_BACKEND == "cli":
        from app.services import llm_cli

        parsed = llm_cli.request_tool_call(
            model=model,
            system=system,
            messages=messages,
            tool=tool,
            max_tokens=max_tokens,
        )
        # The CLI returns no tool_use block, so synthesize the continuation
        # fields. raw_content is a text block holding the JSON the model
        # produced, which is what the regeneration loop needs to echo back.
        return ToolCallResult(
            input=parsed,
            tool_use_id=f"cli_{tool_name}",
            raw_content=[{"type": "text", "text": json.dumps(parsed)}],
        )

    response = None
    for attempt in range(rate_limit_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
            )  # type: ignore[call-overload]
            break
        except RateLimitError:
            if attempt < rate_limit_retries - 1:
                logger.warning(
                    "Rate limited calling tool '%s' (attempt %d/%d), waiting %.0fs",
                    tool_name,
                    attempt + 1,
                    rate_limit_retries,
                    rate_limit_wait,
                )
                time.sleep(rate_limit_wait)
            else:
                logger.error(
                    "Rate limit exhausted after %d attempts calling tool '%s'",
                    rate_limit_retries,
                    tool_name,
                )
                raise

    # The loop either breaks with a response or re-raises the RateLimitError.
    assert response is not None

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return ToolCallResult(
                input=dict(block.input),
                tool_use_id=block.id,
                raw_content=list(response.content),
            )

    raise ValueError(f"Model did not call the required tool '{tool_name}'")


def complete_text(
    client: Anthropic,
    *,
    model: str,
    system: Any,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    """Return the assistant's reply as plain text, honouring ``LLM_BACKEND``.

    The text-completion twin of :func:`request_tool_call`, for the call sites
    that parse JSON out of prose rather than forcing a tool call (analysis chat
    and manipulation parsing). Keeping both backends behind one helper means
    those services never branch on the backend themselves.

    Raises ``ValueError`` if the API response carries no text block.
    """
    if settings.LLM_BACKEND == "cli":
        from app.services import llm_cli

        return llm_cli.complete_text(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,  # type: ignore[arg-type]
    )
    text_block = next((b for b in response.content if hasattr(b, "text")), None)
    if text_block is None:
        raise ValueError("No text content in AI response")
    return str(text_block.text)


def coerce_confidence(value: Any) -> float | None:
    """Normalize a model-reported confidence to a [0, 1] float, or None.

    Forced tool use guarantees a tool call but not that every field matches its
    declared type, so a model may report a percentage (0-100) instead of a
    fraction, an out-of-range number, or something non-numeric. Treat any finite
    value above 1 as a percentage; non-numeric, absent, or non-finite values
    return None so callers can omit a confidence indicator (or fall back to a
    default) rather than surface a fake or out-of-range number.
    """
    try:
        c = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(c):
        return None
    if c > 1.0:
        c = c / 100.0
    return max(0.0, min(1.0, c))
