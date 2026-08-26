"""AI-powered data analysis — plan, validate, execute, narrate.

The model is used twice and never as a calculator:

1. **Plan** — given the question and the dataset profile, the model emits an
   :mod:`app.services.analysis_spec` spec: which operations to run, over which
   columns. No numbers.
2. **Validate** — the spec is checked against the operation whitelist and the
   dataframe's real columns and dtypes. A rejected spec is regenerated with the
   specific failures fed back, the same loop the cleaning planner uses.
3. **Execute** — :mod:`app.services.analysis_executor` runs the operations in
   pandas and scipy over the *full* dataframe. Every reported number originates
   here.
4. **Narrate** — the model receives the computed results and writes the answer,
   under a prompt that forbids introducing any figure it was not given.

This replaces an earlier implementation that sent a profile and 20 sample rows
to the model and asked it to produce the answer *and* the chart values, which
meant every rendered figure was generated rather than measured.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
from anthropic import Anthropic

from app.config import settings
from app.services.analysis_executor import (
    ExecutionError,
    OperationResult,
    build_chart,
    execute_spec,
)
from app.services.analysis_spec import ColumnRoles, describe_capabilities, validate_spec
from app.services.structured_output import complete_text

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_PLAN_PROMPT_PATH = _PROMPTS_DIR / "analysis_plan.txt"
_NARRATE_PROMPT_PATH = _PROMPTS_DIR / "analysis_narrate.txt"

_prompt_cache: dict[str, str] = {}
_anthropic_client: Anthropic | None = None

# How many times to regenerate a spec that fails validation before giving up.
MAX_PLAN_ATTEMPTS = 3

# Rows of the dataset shown to the planner so it can see value shapes. The
# planner must not draw conclusions from these — the prompt says so explicitly.
PLANNER_SAMPLE_ROWS = 10

_UNAVAILABLE = "Sorry, the analysis service is temporarily unavailable."


def _get_client() -> Anthropic:
    """Return a lazily-initialized Anthropic client singleton."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY or None)
    return _anthropic_client


def _load_prompt(path: Path) -> str:
    cached = _prompt_cache.get(str(path))
    if cached is None:
        cached = path.read_text(encoding="utf-8")
        _prompt_cache[str(path)] = cached
    return cached


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from text, handling optional markdown code fences."""
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# 1. Plan
# ---------------------------------------------------------------------------


def _build_planner_context(profile_json: dict[str, Any], df: pd.DataFrame) -> str:
    """Describe the dataset to the planner: real dtypes, profile, a small sample.

    Dtypes come from the dataframe rather than the profile because the validator
    checks against the dataframe — showing the planner anything else would let it
    propose specs that are then rejected for reasons it could not see.
    """
    dtypes = {str(col): str(df[col].dtype) for col in df.columns}
    sample = df.head(PLANNER_SAMPLE_ROWS).to_dict(orient="records")
    return "\n".join(
        [
            f"=== Dataset ({len(df)} rows, {len(df.columns)} columns) ===",
            "",
            "Column dtypes (authoritative — the validator uses these):",
            json.dumps(dtypes, indent=2, default=str),
            "",
            "=== Profile ===",
            json.dumps(profile_json, indent=2, default=str),
            "",
            f"=== Sample ({min(PLANNER_SAMPLE_ROWS, len(df))} rows — shape only, not evidence) ===",
            json.dumps(sample, indent=2, default=str),
        ]
    )


def generate_spec(
    question: str,
    profile_json: dict[str, Any],
    df: pd.DataFrame,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask the model for an analysis spec, regenerating until it validates.

    Raises ``ValueError`` when no attempt produces a valid spec.
    """
    system = _load_prompt(_PLAN_PROMPT_PATH).replace("{capabilities}", describe_capabilities())
    roles = ColumnRoles.from_dataframe(df)
    context = _build_planner_context(profile_json, df)

    conversation: list[dict[str, Any]] = []
    for message in history:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role in ("user", "assistant") and content:
            conversation.append({"role": role, "content": content})
    conversation.append({"role": "user", "content": question})

    last_problems = "unknown"
    for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
        raw = complete_text(
            _get_client(),
            model=settings.ANALYSIS_MODEL,
            max_tokens=2048,
            system=[
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": context},
            ],
            messages=conversation,
        )

        spec = _extract_json(raw)
        if spec is None:
            # Log the head of the reply: a spec that will not parse is almost
            # always a preamble or a truncation, and the two need different fixes.
            logger.warning("Planner reply did not parse as JSON: %r", raw[:200])
            last_problems = "the response was not valid JSON"
        else:
            problems = validate_spec(spec, roles)
            if not problems:
                logger.info(
                    "Analysis spec validated on attempt %d (ops=%d, refusal=%s)",
                    attempt,
                    len(spec.get("operations", [])),
                    bool(spec.get("refusal")),
                )
                return spec
            last_problems = "\n".join(problems)

        if attempt < MAX_PLAN_ATTEMPTS:
            logger.warning(
                "Analysis spec attempt %d/%d rejected: %s",
                attempt,
                MAX_PLAN_ATTEMPTS,
                last_problems[:300],
            )
            conversation.append({"role": "assistant", "content": raw})
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        "That spec was rejected by the validator:\n"
                        f"{last_problems}\n\n"
                        "Return a corrected spec. Use only the operations and the exact "
                        "column names available. If the question genuinely cannot be "
                        "answered from this dataset, return a refusal instead."
                    ),
                }
            )

    raise ValueError(
        f"Analysis spec failed validation after {MAX_PLAN_ATTEMPTS} attempts: {last_problems[:500]}"
    )


# ---------------------------------------------------------------------------
# 4. Narrate
# ---------------------------------------------------------------------------


def _results_payload(results: list[OperationResult]) -> str:
    """Serialize computed results for the narrator.

    Carries provenance (n, n_excluded, notes) and any statistical test output,
    because the narrator prompt requires reporting them.
    """
    return json.dumps(
        [
            {
                "label": result.label,
                "operation": result.op,
                "columns": result.columns,
                "rows": result.rows,
                "total_rows": result.total_rows,
                "n": result.n,
                "n_excluded": result.n_excluded,
                "notes": result.notes,
                "statistics": result.stats,
            }
            for result in results
        ],
        indent=2,
        default=str,
    )


def narrate_results(question: str, spec: dict[str, Any], results: list[OperationResult]) -> str:
    """Turn computed results into prose. The model sees numbers, never raw data."""
    system = _load_prompt(_NARRATE_PROMPT_PATH)
    payload = (
        f"=== Question ===\n{question}\n\n"
        f"=== Why these operations ===\n{spec.get('rationale', '(not stated)')}\n\n"
        f"=== Computed results ===\n{_results_payload(results)}"
    )

    raw = complete_text(
        _get_client(),
        model=settings.ANALYSIS_MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": payload}],
    )

    parsed = _extract_json(raw)
    if parsed and isinstance(parsed.get("answer"), str):
        return str(parsed["answer"])
    # The narrator returning prose instead of JSON is harmless — the prose IS
    # the answer. Only its wrapper was wrong.
    logger.warning("Narrator did not return JSON; using the raw text as the answer.")
    return raw.strip()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def analyze_data(
    question: str,
    profile_json: dict[str, Any],
    df: pd.DataFrame,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Answer *question* about *df* by computing, then explaining.

    Returns the API's established shape — ``{answer, charts, tables}`` — so the
    frontend contract is unchanged. What changed is that the values are measured.

    This is a sync function — call via ``asyncio.to_thread()`` from async code.
    """
    try:
        spec = generate_spec(question, profile_json, df, history)
    except Exception:
        logger.exception("Analysis planning failed")
        return {"answer": _UNAVAILABLE, "charts": [], "tables": []}

    if spec.get("refusal"):
        # A refusal is a real answer: the model determined the data cannot
        # support the question. Surface it rather than inventing a substitute.
        logger.info("Analysis declined: %s", str(spec["refusal"])[:200])
        return {"answer": str(spec["refusal"]), "charts": [], "tables": []}

    try:
        results = execute_spec(df, spec)
    except ExecutionError as exc:
        logger.warning("Analysis execution failed: %s", exc)
        return {
            "answer": (
                "I planned an analysis for that question but it could not be computed "
                f"on this dataset: {exc}"
            ),
            "charts": [],
            "tables": [],
        }
    except Exception:
        logger.exception("Analysis execution raised unexpectedly")
        return {"answer": _UNAVAILABLE, "charts": [], "tables": []}

    try:
        answer = narrate_results(question, spec, results)
    except Exception:
        logger.exception("Analysis narration failed")
        # The computation succeeded; returning the tables without prose beats
        # discarding real results because the wording step failed.
        answer = (
            "The analysis completed, but the summary could not be generated. "
            "The computed results are below."
        )

    chart = build_chart(spec.get("chart"), results)
    return {
        "answer": answer,
        "charts": [chart] if chart else [],
        "tables": [result.to_table() for result in results],
    }
