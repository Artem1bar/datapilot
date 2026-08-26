"""Claude Code CLI backend — bills model calls to a Claude subscription.

Selected with ``LLM_BACKEND=cli``. Every call shells out to the local ``claude``
binary in print mode instead of hitting the Anthropic API, so usage draws on the
operator's Claude subscription rather than an API key.

**Closed testing only.** This drives one human's personal subscription: it does
not scale past the operator, and serving real beta users through it would be
reselling subscription capacity. ``Settings.production_secret_problems`` refuses
to boot production with this backend selected. The API backend stays the
production path; this is a switch, not a replacement.

Why the invocation is stripped down
-----------------------------------
A default ``claude -p`` loads the whole coding-agent harness — tool schemas, MCP
servers, skills, CLAUDE.md discovery — which measured ~50k tokens of preamble on
a one-word reply, and puts a coding agent's instructions in front of a
data-cleaning prompt. Four flags remove all of it:

===========================  =========================================
``--system-prompt``          replaces the coding-agent system prompt
``--setting-sources ""``     no CLAUDE.md, skills, settings, or hooks
``--strict-mcp-config``      no MCP servers
``--tools ""``               no built-in tool schemas
===========================  =========================================

Measured on this machine, that takes the same one-word reply from ~50k tokens to
~600 — the prompt itself and nothing else.

Structured output differs from the API path
-------------------------------------------
The API backend forces a tool call, so the SDK hands back an already-parsed dict
(see :mod:`app.services.structured_output`). The CLI exposes no equivalent —
custom tools would have to come back through an MCP server, reintroducing the
overhead the flags above just removed. So :func:`request_tool_call` instead
renders the tool's JSON Schema into the prompt, demands a bare JSON object, and
retries on a parse failure. That is strictly weaker than forced tool use, which
is part of why this backend is not the production path.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Flags that strip the coding-agent harness. See the module docstring.
_STRIP_FLAGS = (
    "--setting-sources",
    "",
    "--strict-mcp-config",
    "--tools",
    "",
)


class ClaudeCLIError(RuntimeError):
    """The ``claude`` binary failed, timed out, or returned an error result."""


def _resolve_binary() -> str:
    """Return an absolute path to the ``claude`` binary.

    Raises ``ClaudeCLIError`` when it is not on PATH, so a misconfigured
    ``LLM_BACKEND=cli`` fails with a clear message instead of ``FileNotFoundError``.
    """
    resolved = shutil.which(settings.CLAUDE_CLI_PATH)
    if resolved is None:
        raise ClaudeCLIError(
            f"Claude CLI not found (CLAUDE_CLI_PATH={settings.CLAUDE_CLI_PATH!r}). "
            "Install Claude Code or set LLM_BACKEND=api."
        )
    return resolved


def _subprocess_env() -> dict[str, str]:
    """Environment for the child, with API-key variables removed.

    The CLI prefers ``ANTHROPIC_API_KEY`` over subscription auth when both are
    available. Leaving it set would silently bill the API — the exact thing this
    backend exists to avoid — so it is stripped from the child's environment.
    """
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    return env


def _flatten_messages(messages: list[dict[str, Any]]) -> str:
    """Render a Messages-API history as a single prompt string.

    ``claude -p`` takes one prompt, not a role-tagged array, so a multi-turn
    history is flattened into a labelled transcript.

    Content that is a list of blocks is reduced to text. ``tool_result`` blocks
    are rendered alongside ``text`` blocks, not dropped: the cleaning planner's
    regeneration loop feeds validator rejections back as ``tool_result``, and
    losing them would make the model retry against no feedback at all.
    """
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            chunks: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    chunks.append(str(block.get("text", "")))
                elif block.get("type") == "tool_result":
                    inner = block.get("content", "")
                    chunks.append(inner if isinstance(inner, str) else json.dumps(inner))
            text = "\n".join(chunks)
        else:
            text = str(content)
        if not text.strip():
            continue
        parts.append(text if len(messages) == 1 else f"[{role}]\n{text}")
    return "\n\n".join(parts)


def _system_to_text(system: Any) -> str:
    """Reduce a ``system`` argument to plain text.

    Call sites pass either a string or the API's list-of-blocks form (used to
    attach ``cache_control``). The CLI takes a single ``--system-prompt`` string,
    and its own prompt caching is handled upstream, so blocks are concatenated
    and any cache directives dropped.
    """
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(
            block.get("text", "")
            for block in system
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(system)


def _run(prompt: str, *, model: str, system: str) -> str:
    """Invoke the CLI once and return the assistant's text.

    The prompt goes over stdin — dataset profiles routinely exceed a comfortable
    argv length. ``cwd`` is a throwaway temp directory so nothing in the repo is
    discoverable even if a setting source were somehow loaded.
    """
    argv = [
        _resolve_binary(),
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        "--system-prompt",
        system,
        *_STRIP_FLAGS,
    ]

    with tempfile.TemporaryDirectory(prefix="datapilot-cli-") as workdir:
        try:
            completed = subprocess.run(  # noqa: S603 - argv is built here, never shell
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=settings.CLAUDE_CLI_TIMEOUT_SECONDS,
                env=_subprocess_env(),
                cwd=workdir,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCLIError(
                f"Claude CLI timed out after {settings.CLAUDE_CLI_TIMEOUT_SECONDS}s"
            ) from exc

    if completed.returncode != 0:
        raise ClaudeCLIError(
            f"Claude CLI exited {completed.returncode}: {completed.stderr.strip()[:500]}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCLIError(
            f"Claude CLI returned non-JSON output: {completed.stdout[:300]!r}"
        ) from exc

    if payload.get("is_error"):
        raise ClaudeCLIError(f"Claude CLI reported an error: {payload.get('result')!r}")

    result = payload.get("result")
    if not isinstance(result, str):
        raise ClaudeCLIError(f"Claude CLI returned no result text: {payload!r}")

    usage = payload.get("usage") or {}
    logger.info(
        "Claude CLI call complete (model=%s, in=%s, out=%s, ms=%s)",
        model,
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        payload.get("duration_ms"),
    )
    return result


def complete_text(
    *,
    model: str,
    system: Any,
    messages: list[dict[str, Any]],
    max_tokens: int,  # noqa: ARG001 - API-backend parity; the CLI has no equivalent knob
) -> str:
    """Return the assistant's reply as text — the CLI twin of ``messages.create``.

    ``max_tokens`` is accepted so both backends share one signature, but the CLI
    exposes no output cap; it is ignored rather than silently approximated.
    """
    return _run(
        _flatten_messages(messages),
        model=model,
        system=_system_to_text(system),
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull a single JSON object out of a model reply, or return None.

    Handles the two shapes a JSON-only instruction still produces: a bare object,
    or one wrapped in a markdown fence. Anything else returns None so the caller
    can retry rather than raise.
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        # Drop the opening fence (with optional language tag) and closing fence.
        candidate = candidate.split("\n", 1)[-1]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[: -len("```")]
        candidate = candidate.strip()

    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _json_instruction(tool: dict[str, Any]) -> str:
    """Build the system-prompt suffix that stands in for forced tool use."""
    schema = json.dumps(tool.get("input_schema", {}), indent=2)
    return (
        f"\n\n=== REQUIRED OUTPUT FORMAT ===\n"
        f"Respond with a single raw JSON object conforming to this JSON Schema:\n\n"
        f"{schema}\n\n"
        f"Output the JSON object and nothing else — no prose, no explanation, and "
        f"no markdown code fences. The response must start with '{{' and end with '}}'."
    )


def request_tool_call(
    *,
    model: str,
    system: Any,
    messages: list[dict[str, Any]],
    tool: dict[str, Any],
    max_tokens: int,  # noqa: ARG001 - API-backend parity; the CLI has no equivalent knob
    parse_retries: int = 2,
) -> dict[str, Any]:
    """Return a structured dict, standing in for the API's forced tool call.

    Renders ``tool``'s schema into the system prompt and parses the reply. On a
    parse failure the call is retried (``parse_retries`` attempts total) with a
    blunter instruction appended, because the usual failure is conversational
    padding around otherwise-valid JSON.

    Raises ``ClaudeCLIError`` when no attempt yields a JSON object.
    """
    base_system = _system_to_text(system) + _json_instruction(tool)
    prompt = _flatten_messages(messages)

    for attempt in range(parse_retries):
        system_text = base_system
        if attempt:
            system_text += (
                "\n\nYour previous response could not be parsed as JSON. "
                "Return ONLY the JSON object this time."
            )
        text = _run(prompt, model=model, system=system_text)
        parsed = _extract_json_object(text)
        if parsed is not None:
            return parsed
        logger.warning(
            "Claude CLI returned unparseable JSON for tool '%s' (attempt %d/%d)",
            tool.get("name"),
            attempt + 1,
            parse_retries,
        )

    raise ClaudeCLIError(
        f"Claude CLI did not return parseable JSON for tool "
        f"{tool.get('name')!r} after {parse_retries} attempts"
    )
