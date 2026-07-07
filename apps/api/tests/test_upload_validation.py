"""Upload size cap + magic-byte validation on the dataset upload paths."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers import datasets as datasets_mod
from app.routers.datasets import _validate_upload, upload_dataset


def test_validate_upload_rejects_oversize(monkeypatch):
    monkeypatch.setattr(datasets_mod.settings, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(HTTPException) as exc:
        _validate_upload(b"12345678901", "x.csv")  # 11 bytes > 10
    assert exc.value.status_code == 413


def test_validate_upload_rejects_content_extension_mismatch():
    with pytest.raises(HTTPException) as exc:
        _validate_upload(b"this is plainly not an xlsx", "data.xlsx")
    assert exc.value.status_code == 400


def test_validate_upload_rejects_empty_file():
    with pytest.raises(HTTPException) as exc:
        _validate_upload(b"", "data.csv")
    assert exc.value.status_code == 400


def test_validate_upload_accepts_valid_csv():
    _validate_upload(b"a,b\n1,2\n", "data.csv")  # text format, no raise


def test_validate_upload_accepts_valid_xlsx_magic():
    _validate_upload(b"PK\x03\x04and the rest", "data.xlsx")  # OOXML magic, no raise


@pytest.mark.asyncio
async def test_upload_dataset_rejects_bad_content_before_storage():
    file = MagicMock()
    file.read = AsyncMock(return_value=b"definitely not a real xlsx")
    file.filename = "evil.xlsx"
    file.content_type = "application/octet-stream"
    db = AsyncMock()
    db.add = MagicMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    with patch("app.routers.datasets.upload_file_bytes") as mock_upload:
        with pytest.raises(HTTPException) as exc:
            await upload_dataset(user, db, file)

    assert exc.value.status_code == 400
    mock_upload.assert_not_called()  # never reached storage
    db.add.assert_not_called()  # never created a dataset row
