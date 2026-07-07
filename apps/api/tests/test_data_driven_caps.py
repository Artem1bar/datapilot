"""Data-driven caps: robust profile stats replace hardcoded dollar folklore."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.tasks.profile_task import _compute_profile

PROMPT_DIR = Path(__file__).resolve().parent.parent / "app" / "prompts"


def test_profile_includes_robust_upper_tail_stats():
    df = pd.DataFrame({"amount": [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]})
    stats = _compute_profile(df)["columns"]["amount"]
    assert {"p95", "p99", "mad"} <= stats.keys()
    assert stats["max"] == 100
    assert stats["mad"] > 0
    assert stats["p99"] >= stats["p95"] >= stats["q75"]


def test_non_numeric_column_has_no_robust_stats():
    df = pd.DataFrame({"city": ["a", "b", "c"]})
    stats = _compute_profile(df)["columns"]["city"]
    assert "p99" not in stats


def test_prompts_have_no_hardcoded_dollar_caps():
    # The removed cap table hardcoded per-domain dollar ceilings; caps must now
    # be derived from each column's own distribution instead.
    banned = ["50000", "25000", "100000", "gambling", "Hotel/accommodation"]
    for name in ("cleaning_system.txt", "verification_system.txt"):
        text = (PROMPT_DIR / name).read_text(encoding="utf-8").lower()
        for token in banned:
            assert token.lower() not in text, f"{name} still contains folklore {token!r}"
