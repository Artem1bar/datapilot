"""Guard: every AI service's ``_get_client`` reads a real settings attribute.

Regression for a bug where ``manipulation._get_client`` referenced
``settings.anthropic_api_key`` (lowercase) instead of ``ANTHROPIC_API_KEY`` —
an ``AttributeError`` that only surfaced at runtime (a 500 on every parse)
because the unit tests mock the Anthropic client and never hit ``_get_client``.
Here we exercise the real ``_get_client`` with a patched key so the wrong
attribute name fails in CI, not in production.
"""

from __future__ import annotations

import importlib

import pytest

AI_SERVICE_MODULES = [
    "app.services.manipulation",
    "app.services.data_dictionary",
    "app.services.analysis",
]


@pytest.mark.parametrize("module_path", AI_SERVICE_MODULES)
def test_get_client_reads_valid_settings_attribute(module_path: str, monkeypatch) -> None:
    module = importlib.import_module(module_path)
    # Reset the cached singleton so _get_client actually constructs a client.
    monkeypatch.setattr(module, "_anthropic_client", None)
    monkeypatch.setattr(module.settings, "ANTHROPIC_API_KEY", "sk-test-key")

    client = module._get_client()

    assert client is not None
    # Leave the singleton reset so other tests re-read patched settings.
    monkeypatch.setattr(module, "_anthropic_client", None)
