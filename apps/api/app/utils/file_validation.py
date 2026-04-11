"""File content validation using magic bytes.

Validates that uploaded file content matches its declared extension
before parsing, preventing content-type confusion attacks.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Magic byte signatures for supported file types
_MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    ".xlsx": [b"PK\x03\x04"],  # ZIP archive (OOXML)
    ".xls": [b"\xd0\xcf\x11\xe0"],  # OLE2 Compound Document
    ".parquet": [b"PAR1"],
    ".json": [b"{", b"["],  # JSON starts with { or [
}

# Extensions that are plain text and cannot be validated by magic bytes
_TEXT_EXTENSIONS = {".csv", ".tsv", ".tab", ".txt"}


def validate_file_content(file_bytes: bytes, filename: str) -> bool:
    """Validate that file content matches its extension using magic bytes.

    Returns True if the content is valid or if the extension is a text
    format (which cannot be reliably validated by magic bytes).

    Returns False if the magic bytes don't match the expected signature.
    """
    if not file_bytes:
        logger.warning("Empty file content for %s", filename)
        return False

    ext = _get_extension(filename)

    # Text formats can't be validated by magic bytes
    if ext in _TEXT_EXTENSIONS:
        return True

    signatures = _MAGIC_SIGNATURES.get(ext)
    if signatures is None:
        # Unknown extension — allow but log
        logger.info("No magic byte signature defined for extension '%s'", ext)
        return True

    # Check if file starts with any valid signature
    for sig in signatures:
        if file_bytes[:len(sig)] == sig:
            return True

    logger.warning(
        "File content mismatch for %s: expected one of %s, got %s",
        filename,
        [sig.hex() for sig in signatures],
        file_bytes[:8].hex(),
    )
    return False


def _get_extension(filename: str) -> str:
    """Extract lowercase file extension from filename."""
    from pathlib import Path

    return Path(filename).suffix.lower()
