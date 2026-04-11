"""Dataset operation history — tracks every mutation for undo/redo."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def create_history_entry(
    dataset_id: str,
    operation_type: str,
    description: str,
    snapshot_key: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a history entry dict (stored in dataset's profile_json.history)."""
    return {
        "id": str(uuid.uuid4()),
        "dataset_id": dataset_id,
        "operation_type": operation_type,
        "description": description,
        "snapshot_key": snapshot_key,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
