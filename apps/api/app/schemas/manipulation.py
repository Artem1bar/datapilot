"""Pydantic schemas for spreadsheet manipulation."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ManipulationOpType(StrEnum):
    delete_columns = "delete_columns"
    rename_column = "rename_column"
    sort = "sort"
    filter_rows = "filter_rows"
    add_column = "add_column"
    merge_columns = "merge_columns"
    format_column = "format_column"
    move_column = "move_column"
    split_column = "split_column"
    drop_duplicates = "drop_duplicates"
    fill_nulls = "fill_nulls"
    cast_type = "cast_type"
    reorder_columns = "reorder_columns"


class ManipulationOp(BaseModel):
    op_type: ManipulationOpType
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class ManipulationParseRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000)


class ManipulationApplyRequest(BaseModel):
    operations: list[ManipulationOp] = Field(..., min_length=1)


class ManipulationUndoRequest(BaseModel):
    snapshot_id: str


class ManipulationPreview(BaseModel):
    operations: list[ManipulationOp]
    preview_before: list[dict[str, Any]] = Field(default_factory=list)
    preview_after: list[dict[str, Any]] = Field(default_factory=list)
    affected_columns: list[str] = Field(default_factory=list)
    affected_row_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    confirmation_required: bool = False


class ManipulationResult(BaseModel):
    success: bool
    snapshot_id: str = ""
    new_row_count: int = 0
    new_col_count: int = 0
    columns_added: list[str] = Field(default_factory=list)
    columns_removed: list[str] = Field(default_factory=list)
    columns_renamed: dict[str, str] = Field(default_factory=dict)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
