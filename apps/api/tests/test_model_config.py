"""Model tiers are config-driven, not hardcoded in each service."""

from __future__ import annotations

from pathlib import Path

from app.config import settings

SERVICES_DIR = Path(__file__).resolve().parent.parent / "app" / "services"


def test_model_tier_defaults_present():
    # Data-mutating stages run on the strongest model; analysis is interactive
    # chat, where Sonnet 5's latency matters more than Opus depth.
    assert settings.CLEANING_MODEL == "claude-opus-5"
    assert settings.VERIFICATION_MODEL == "claude-opus-5"
    assert settings.MANIPULATION_MODEL == "claude-opus-5"
    assert settings.ANALYSIS_MODEL == "claude-sonnet-5"
    assert settings.DICTIONARY_MODEL


def test_services_do_not_hardcode_model_ids():
    offenders = [
        py.name
        for py in SERVICES_DIR.glob("*.py")
        if 'model="claude-' in py.read_text(encoding="utf-8")
    ]
    assert not offenders, f"services hardcode model ids: {offenders}"
