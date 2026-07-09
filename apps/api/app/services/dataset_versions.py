"""Which file currently represents a dataset.

Cleaning never mutates the uploaded file — each completed clean job writes
its own cleaned object (per-job key) and records it in ``result_json``.
The "current" bytes for a dataset are therefore: the newest completed,
non-reverted clean job's ``cleaned_r2_key``, or the original upload when
no such job exists. Every consumer (dataset download, export) must pick
through this one function so revert semantics stay consistent.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def pick_effective_r2_key(original_key: str, clean_jobs: Iterable[Any]) -> str:
    """Return the storage key that currently represents the dataset.

    *clean_jobs* must be **completed** clean jobs ordered **newest first**.
    Reverted jobs and jobs without a recorded cleaned key are skipped.
    """
    for job in clean_jobs:
        result_json = getattr(job, "result_json", None) or {}
        if result_json.get("reverted"):
            continue
        key = result_json.get("cleaned_r2_key")
        if key:
            return key
    return original_key
