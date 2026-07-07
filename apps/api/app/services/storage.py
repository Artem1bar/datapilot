"""S3 / MinIO client wrapper with presigned URL generation."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings


def _build_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )


_client = None


def get_s3_client():
    global _client
    if _client is None:
        _client = _build_s3_client()
    return _client


def generate_upload_key(user_id: uuid.UUID, filename: str) -> str:
    """Return a unique S3 object key for a user upload."""
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    unique = uuid.uuid4().hex[:8]
    # Strip directory components to prevent path traversal, then sanitize
    safe_name = Path(filename).name
    safe_name = re.sub(r"[^\w.\-]", "_", safe_name)
    return f"uploads/{user_id}/{ts}_{unique}_{safe_name}"


def create_presigned_upload_url(
    key: str,
    content_type: str = "text/csv",
    expires_in: int = 3600,
) -> str:
    """Generate a presigned PUT URL for uploading to S3/MinIO/R2."""
    client = get_s3_client()
    url: str = client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )
    return url


def create_presigned_download_url(
    key: str,
    expires_in: int = 3600,
) -> str:
    """Generate a presigned GET URL for downloading from S3/MinIO/R2."""
    client = get_s3_client()
    url: str = client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": key,
        },
        ExpiresIn=expires_in,
    )
    return url


def upload_file_bytes(
    key: str, data: bytes, content_type: str = "application/octet-stream"
) -> None:
    """Upload bytes directly to S3/MinIO/R2."""
    client = get_s3_client()
    client.put_object(Bucket=settings.R2_BUCKET_NAME, Key=key, Body=data, ContentType=content_type)


def download_file_bytes(key: str) -> bytes:
    """Download an object from S3/MinIO/R2 and return its bytes."""
    client = get_s3_client()
    response = client.get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    return response["Body"].read()


def delete_object(key: str) -> None:
    """Delete an object from S3/MinIO/R2."""
    client = get_s3_client()
    client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
