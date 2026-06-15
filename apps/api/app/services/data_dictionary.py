"""Generate AI-powered data dictionaries for datasets."""
from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_anthropic_client: Anthropic | None = None


def _get_client() -> Anthropic:
    """Return a lazily-initialized Anthropic client singleton."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY or None)
    return _anthropic_client


_SYSTEM_PROMPT = """You are a data documentation expert. Given a dataset profile with column names, types, sample values, and statistics, generate a comprehensive data dictionary.

For each column, provide:
1. "description": A clear, 1-2 sentence description of what the column contains
2. "business_meaning": The business context/purpose of this field
3. "data_type": The recommended data type (string, integer, float, datetime, boolean, categorical)
4. "constraints": Any inferred constraints (not null, unique, range, enum values)
5. "notes": Any additional observations (e.g., "Contains PII", "Needs standardization")

Return a JSON object with a "columns" key containing an array of column dictionaries, and a "dataset_summary" key with a 2-3 sentence overview.

Example output format:
{
  "dataset_summary": "This dataset contains customer order information...",
  "columns": [
    {
      "name": "customer_id",
      "description": "Unique identifier for each customer",
      "business_meaning": "Primary key linking to the customer master table",
      "data_type": "integer",
      "constraints": ["not null", "unique"],
      "notes": "System-generated sequential ID"
    }
  ]
}"""


def generate_data_dictionary(
    profile_json: dict,
    sample_rows: list[dict],
) -> dict[str, Any]:
    """Generate an AI-powered data dictionary.

    Sync function -- call via asyncio.to_thread().
    """
    client = _get_client()

    # Build context
    columns_info = []
    for col_name, col_data in profile_json.get("columns", {}).items():
        info = {
            "name": col_name,
            "dtype": col_data.get("dtype", "unknown"),
            "null_pct": col_data.get("null_pct", 0),
            "unique_count": col_data.get("unique_count", 0),
        }
        if "top_values" in col_data:
            info["top_values"] = dict(list(col_data["top_values"].items())[:5])
        if "mean" in col_data:
            info["stats"] = {
                "mean": col_data.get("mean"),
                "min": col_data.get("min"),
                "max": col_data.get("max"),
            }
        columns_info.append(info)

    context = json.dumps({
        "row_count": profile_json.get("row_count", 0),
        "col_count": profile_json.get("col_count", 0),
        "columns": columns_info,
        "sample_rows": sample_rows[:5],
    }, default=str)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Generate a data dictionary for this dataset:\n{context}"}],
        )
        text = response.content[0].text.strip()

        # Parse JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        return json.loads(text)
    except Exception:
        logger.exception("Failed to generate data dictionary")
        return {"dataset_summary": "Failed to generate data dictionary", "columns": []}
