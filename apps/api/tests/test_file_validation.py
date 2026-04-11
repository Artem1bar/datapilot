"""Unit tests for file content validation."""

from __future__ import annotations

from app.utils.file_validation import validate_file_content


class TestValidateFileContent:
    def test_csv_always_valid(self):
        assert validate_file_content(b"col1,col2\n1,2", "data.csv") is True

    def test_tsv_always_valid(self):
        assert validate_file_content(b"col1\tcol2\n1\t2", "data.tsv") is True

    def test_json_valid_object(self):
        assert validate_file_content(b'{"key": "value"}', "data.json") is True

    def test_json_valid_array(self):
        assert validate_file_content(b'[1, 2, 3]', "data.json") is True

    def test_json_invalid_magic(self):
        assert validate_file_content(b"not json", "data.json") is False

    def test_xlsx_valid_magic(self):
        # XLSX files are ZIP archives starting with PK\x03\x04
        content = b"PK\x03\x04" + b"\x00" * 100
        assert validate_file_content(content, "data.xlsx") is True

    def test_xlsx_invalid_magic(self):
        assert validate_file_content(b"not a zip", "data.xlsx") is False

    def test_parquet_valid_magic(self):
        content = b"PAR1" + b"\x00" * 100
        assert validate_file_content(content, "data.parquet") is True

    def test_parquet_invalid_magic(self):
        assert validate_file_content(b"NOT_PARQUET", "data.parquet") is False

    def test_xls_valid_magic(self):
        content = b"\xd0\xcf\x11\xe0" + b"\x00" * 100
        assert validate_file_content(content, "data.xls") is True

    def test_empty_file_rejected(self):
        assert validate_file_content(b"", "data.csv") is False

    def test_unknown_extension_allowed(self):
        assert validate_file_content(b"whatever", "data.unknown") is True
