"""Claude-powered verification agent for post-cleaning quality assessment.

Invoked only when the deterministic verification fails or audit completeness
is low. Uses claude-sonnet-4-6 for thorough analysis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from app.config import settings
from app.services.structured_output import coerce_confidence, request_tool_call

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "verification_system.txt"

# Tool schema Claude must call to report its assessment. Forcing this tool call
# (see structured_output.request_tool_call) means the SDK returns an already-
# parsed dict instead of JSON we have to scrape out of free text.
_VERIFICATION_TOOL: dict[str, Any] = {
    "name": "submit_verification",
    "description": "Report the results of independently verifying the cleaned dataset.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {
                "type": "boolean",
                "description": "True only if no CRITICAL or HIGH issues remain in the cleaned data.",
            },
            "confidence": {
                "type": "number",
                "description": "Your confidence in this assessment, from 0.0 to 1.0.",
            },
            "issues_found": {
                "type": "array",
                "description": "Every remaining data-quality issue you found.",
                "items": {
                    "type": "object",
                    "properties": {
                        "column": {"type": ["string", "null"]},
                        "issue": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        },
                        "detail": {"type": "string"},
                    },
                    "required": ["issue", "severity"],
                },
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
            },
            "remediation_steps": {
                "type": "array",
                "description": "Concrete cleaning steps that fix each CRITICAL/HIGH issue.",
                "items": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string"},
                        "column": {"type": ["string", "null"]},
                        "params": {
                            "type": "object",
                            "description": "Operation-specific parameters.",
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["operation"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["passed", "confidence", "summary"],
    },
}

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentVerificationResult:
    """Result from the Claude verification agent."""

    passed: bool
    confidence: float  # 0.0 – 1.0
    issues_found: tuple[dict[str, Any], ...] = ()
    recommendations: tuple[str, ...] = ()
    remediation_steps: tuple[dict[str, Any], ...] = ()  # concrete steps to fix issues
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Anthropic client (reuses the same singleton pattern as cleaning.py)
# ---------------------------------------------------------------------------

_anthropic_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY or None)
    return _anthropic_client


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------


def run_verification_agent(
    original_quality_flags: dict[str, Any],
    steps_applied: list[dict[str, Any]],
    audit_log_sample: list[dict[str, Any]],
    cleaned_sample_rows: list[dict[str, Any]],
    deterministic_report: dict[str, Any],
) -> AgentVerificationResult:
    """Run the Claude verification agent to independently assess cleaning quality.

    Args:
        original_quality_flags: Quality flags from the original dataset profile.
        steps_applied: List of cleaning steps that were executed.
        audit_log_sample: First N entries of the audit log (truncated for token budget).
        cleaned_sample_rows: Sample rows from the cleaned DataFrame.
        deterministic_report: Serialized VerificationReport from deterministic check.

    Returns:
        AgentVerificationResult with pass/fail, confidence, issues, and recommendations.
    """
    system_prompt = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # Number the steps for traceability
    numbered_steps = []
    for i, step in enumerate(steps_applied, 1):
        numbered_step = dict(step)
        numbered_step["step_number"] = i
        desc = numbered_step.get("description", "")
        if not desc.startswith(f"Step {i}"):
            numbered_step["description"] = f"Step {i}: {desc}"
        numbered_steps.append(numbered_step)

    # ── Payload size management ──
    # Must stay under ~20K input tokens to respect rate limits.
    # Strategy: only send columns that have quality flags (not all 68+ columns).

    # Identify columns mentioned in quality flags
    _meta_keys = {
        "qualtrics_header_row",
        "_dirty_column_names",
        "_empty_columns",
        "_incomplete_responses",
    }
    flagged_cols = {k for k in original_quality_flags if k not in _meta_keys}

    # Context columns (first 3 for identification)
    if cleaned_sample_rows:
        all_cols = list(cleaned_sample_rows[0].keys())
        context_cols = all_cols[:3]
        keep_cols = list(dict.fromkeys(context_cols + sorted(flagged_cols)))
        trimmed_rows = [
            {col: row.get(col) for col in keep_cols if col in row}
            for row in cleaned_sample_rows[:20]  # max 20 rows
        ]
    else:
        trimmed_rows = []

    # Steps: only send last 15 + summary
    if len(numbered_steps) > 20:
        steps_summary = (
            f"(First {len(numbered_steps) - 15} steps omitted. "
            f"Total: {len(numbered_steps)} steps.)\n"
        )
        steps_to_send = numbered_steps[-15:]
    else:
        steps_summary = ""
        steps_to_send = numbered_steps

    # Audit log: max 50 meaningful entries
    max_audit = 50

    # Trim deterministic report — remove verbose step_results, keep summary
    slim_report = {
        k: v
        for k, v in deterministic_report.items()
        if k not in ("step_results",)  # step_results is huge and redundant
    }

    user_message = (
        "## ORIGINAL QUALITY FLAGS\n"
        f"```json\n{json.dumps(original_quality_flags, indent=2, default=str)}\n```\n\n"
        f"## CLEANING STEPS ({len(numbered_steps)} total, showing last {len(steps_to_send)})\n"
        f"{steps_summary}"
        f"```json\n{json.dumps(steps_to_send, indent=2, default=str)}\n```\n\n"
        f"## AUDIT LOG (first {min(len(audit_log_sample), max_audit)} entries)\n"
        f"```json\n{json.dumps(audit_log_sample[:max_audit], indent=2, default=str)}\n```\n\n"
        f"## CLEANED DATA — FLAGGED COLUMNS ONLY ({len(trimmed_rows)} rows, {len(keep_cols) if cleaned_sample_rows else 0} cols)\n"
        f"```json\n{json.dumps(trimmed_rows, indent=2, default=str)}\n```\n\n"
        "## DETERMINISTIC VERIFICATION SUMMARY\n"
        f"```json\n{json.dumps(slim_report, indent=2, default=str)}\n```\n\n"
        "Check every value in the flagged columns for:\n"
        "1. Absurdly large values (>$50K hotels, >$100K gambling)\n"
        "2. String values that should be numeric\n"
        "3. Unresolved quality flags\n"
        "Call the submit_verification tool with your assessment, including "
        "remediation_steps for EVERY CRITICAL/HIGH issue."
    )

    logger.info(
        "Requesting verification from Claude (model=claude-sonnet-4-6, flags=%d, steps=%d, "
        "sample_rows=%d, audit_entries=%d)",
        len(original_quality_flags),
        len(steps_applied),
        len(trimmed_rows),
        min(len(audit_log_sample), max_audit),
    )

    client = _get_client()

    # Force a single submit_verification tool call so the SDK hands back a
    # parsed dict — no JSON scraping. RateLimitError retries are handled inside
    # request_tool_call; a ValueError means the model returned no tool call.
    try:
        result = request_tool_call(
            client,
            model="claude-sonnet-4-6",
            # 8192 (up from 4096) so a plan with many remediation steps isn't
            # truncated mid-tool-call; still well under the streaming threshold.
            max_tokens=8192,
            system=[
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": user_message}],
            tool=_VERIFICATION_TOOL,
        )
    except ValueError:
        logger.error("Verification agent returned no structured tool call")
        return AgentVerificationResult(
            passed=False,
            confidence=0.0,
            issues_found=(
                {
                    "column": None,
                    "issue": "Verification agent returned no structured result",
                    "severity": "HIGH",
                    "detail": "The model did not call the submit_verification tool.",
                },
            ),
            recommendations=("Re-run verification or inspect cleaned data manually",),
            summary="Verification agent did not return a structured result.",
        )

    logger.debug("Verification agent tool input keys: %s", sorted(result.input))
    return _result_from_tool_input(result.input)


def _as_tuple(value: Any) -> tuple[Any, ...]:
    """Coerce a tool-input list field to a tuple; anything non-list becomes empty.

    Forced tool use guarantees a call but not that each field matches its declared
    type — a stray string would otherwise be split into a per-character tuple that
    breaks downstream ``.get("severity")`` access in the remediation loop.
    """
    return tuple(value) if isinstance(value, list) else ()


def _result_from_tool_input(data: dict[str, Any]) -> AgentVerificationResult:
    """Build an AgentVerificationResult from the verification tool's parsed input.

    Fields are defensively coerced because the model's forced tool call is not
    strictly type-checked (Sonnet 4.6 has no strict tool use): a non-numeric or
    out-of-range ``confidence`` must not raise or produce a >100% value, and the
    list fields must not accept a stray scalar.
    """
    return AgentVerificationResult(
        passed=bool(data.get("passed", False)),
        confidence=coerce_confidence(data.get("confidence")) or 0.0,
        issues_found=_as_tuple(data.get("issues_found")),
        recommendations=_as_tuple(data.get("recommendations")),
        remediation_steps=_as_tuple(data.get("remediation_steps")),
        summary=str(data.get("summary") or ""),
    )
