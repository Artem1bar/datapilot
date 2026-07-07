"""User preferences schema — the single source of truth for settings defaults.

Preferences are stored as a JSONB blob on the user row; this model defines the
allowed keys, their types, and their defaults. Reading merges stored values over
these defaults; writing validates the merged result against this model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserPreferences(BaseModel):
    """A user's cleaning/AI preferences. Every field has a safe default."""

    model_config = ConfigDict(extra="forbid")

    # Cleaning behaviour
    cleaning_aggressiveness: Literal["conservative", "standard", "aggressive"] = "standard"
    outlier_method: Literal["mad", "iqr", "none"] = "mad"
    outlier_threshold: float = Field(3.5, ge=0.0, le=100.0)
    cap_strategy: Literal["off", "auto", "manual"] = "auto"
    null_fill_default: Literal["none", "mean", "median", "mode", "zero"] = "none"
    dedup_default: bool = False

    # Planning inputs
    domain: Literal["auto", "survey", "generic"] = "auto"
    custom_instructions: str = Field("", max_length=2000)
    ai_sample_size: int = Field(500, ge=10, le=2000)
    max_remediation_rounds: int = Field(2, ge=0, le=5)

    # Workflow
    review_first: bool = True  # review the plan before applying vs. auto-apply

    # Admin-only model tier overrides (None → use the server default)
    cleaning_model: str | None = Field(default=None, max_length=100)
    verification_model: str | None = Field(default=None, max_length=100)


def merge_preferences(stored: dict | None) -> UserPreferences:
    """Build a fully-defaulted UserPreferences from a (possibly partial) blob.

    Unknown keys in *stored* are ignored so preferences saved by an older schema
    never break reads.
    """
    data = {k: v for k, v in (stored or {}).items() if k in UserPreferences.model_fields}
    return UserPreferences(**data)
