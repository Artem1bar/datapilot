"""Claude-powered verification agent for post-cleaning quality assessment.

Invoked only when the deterministic verification fails or audit completeness
is low. Uses claude-sonnet-4-6 for thorough analysis.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from anthropic import Anthropic, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "verification_system.txt"

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
    _meta_keys = {"qualtrics_header_row", "_dirty_column_names", "_empty_columns", "_incomplete_responses"}
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
        k: v for k, v in deterministic_report.items()
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
        "Return JSON with remediation_steps for EVERY CRITICAL/HIGH issue."
    )

    logger.info(
        "Requesting verification from Claude (model=claude-sonnet-4-6, flags=%d, steps=%d, "
        "sample_rows=%d, audit_entries=%d)",
        len(original_quality_flags), len(steps_applied),
        len(trimmed_rows), min(len(audit_log_sample), max_audit),
    )

    client = _get_client()

    # Retry with backoff on rate limit errors (keep waits short to avoid timeout)
    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            break
        except RateLimitError as e:
            if attempt < max_retries - 1:
                wait_time = 15  # short wait — payload is already trimmed
                logger.warning(
                    "Rate limited on verification attempt %d/%d, waiting %ds: %s",
                    attempt + 1, max_retries, wait_time, e,
                )
                time.sleep(wait_time)
            else:
                logger.error("Rate limit exhausted after %d retries", max_retries)
                raise

    response_text = response.content[0].text
    logger.debug("Verification agent response: %s", response_text[:500])

    parsed = _parse_agent_response(response_text)
    return parsed


def _parse_agent_response(text: str) -> AgentVerificationResult:
    """Parse the JSON response from the verification agent."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove opening fence (e.g. ```json) and closing fence (```)
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Failed to parse verification agent response: %s", text[:300])
        return AgentVerificationResult(
            passed=False,
            confidence=0.0,
            issues_found=({
                "column": None,
                "issue": "Verification agent returned unparseable response",
                "severity": "HIGH",
                "detail": text[:500],
            },),
            recommendations=("Re-run verification or inspect cleaned data manually",),
            summary="Verification agent response could not be parsed.",
        )

    return AgentVerificationResult(
        passed=bool(data.get("passed", False)),
        confidence=float(data.get("confidence", 0.0)),
        issues_found=tuple(data.get("issues_found", [])),
        recommendations=tuple(data.get("recommendations", [])),
        remediation_steps=tuple(data.get("remediation_steps", [])),
        summary=data.get("summary", ""),
    )
